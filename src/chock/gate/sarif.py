"""`chock check --event ci --format sarif`: the ci gates' findings as one SARIF 2.1.0 log, for code scanning.

Output only: the verdicts and the exit code are the ones the gate step itself reaches, and nothing is
logged or annotated here. Paths, escaping and the verdict come from the gate runner, not a second copy.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import quote

from chock import __version__
from chock.gate import runner
from chock.guidance.source import CONTRACT, POLICIES_DIR, GuidanceError, read_text

SARIF_SCHEMA = "https://docs.oasis-open.org/sarif/sarif/v2.1.0/errata01/os/schemas/sarif-schema-2.1.0.json"
INFORMATION_URI = "https://github.com/open-coder-ai/chock"
FINGERPRINT_KEY = "chockFingerprint/v1"
_LEVEL = {runner.ACTION_BLOCK: "error", runner.ACTION_ASK: "warning", runner.ACTION_WARN: "note"}
_CONTRACT_BYTES = 4_000_000
_TEXT_CAP = 1000
_UTF8 = SimpleNamespace(encoding="utf-8")
_UNSAFE = re.compile(r"[\x00-\x1f\x7f-\x9f\u200b-\u200f\u2028-\u202e\u2060-\u2069\ufeff]+")
_CWE_ID = re.compile(r"CWE-(\d+)")
_MATCH = re.compile(r"(?P<path>[^:\s][^:]*?)(?::(?P<line>\d+))?: (?P<text>.*)", re.DOTALL)


def safe_text(value: object, cap: int = _TEXT_CAP) -> str:
    """One line of text with no control, line-break or invisible character and nothing a UTF-8 file cannot hold."""
    text = " ".join(_UNSAFE.sub(" ", str(value)).split())
    text = runner._encodable(text, _UTF8)
    return text if len(text) <= cap else text[: cap - 1] + "…"


@dataclass(frozen=True)
class Item:
    """One finding as a result: the rule it names (empty for the policy as a whole) and where."""

    rule: str
    path: str
    line: int
    message: str
    key: str


def _contract_rules(repo: Path, policy: str) -> list[dict]:
    """The rules of the policy's shipped setup contract; empty when it ships none or it cannot be read."""
    try:
        raw = read_text(repo, f"{POLICIES_DIR}/{policy}/{CONTRACT.format(id=policy)}", _CONTRACT_BYTES)
        rules = json.loads(raw).get("rules") if raw else None
    except (GuidanceError, ValueError, AttributeError, RecursionError):
        return []
    return [r for r in rules if isinstance(r, dict) and isinstance(r.get("id"), str)] if isinstance(rules, list) else []


def _help_uri(rule: dict) -> str | None:
    refs = rule.get("references")
    return (
        next((r for r in refs if isinstance(r, str) and r.startswith("https://") and r.isascii()), None)
        if isinstance(refs, list)
        else None
    )


def _tags(policy: str, rule: dict) -> list[str]:
    cwe = rule.get("cwe")
    ids = [c.get("id") for c in cwe if isinstance(c, dict)] if isinstance(cwe, list) else []
    found = [m for i in ids if isinstance(i, str) and (m := _CWE_ID.fullmatch(i))]
    return ["chock", f"chock/{policy}", *(f"external/cwe/cwe-{m.group(1)}" for m in found)]


def _rule_entry(rule_id: str, policy: str, level: str, text: dict[str, str], extra: dict) -> dict:
    entry: dict = {
        "id": rule_id,
        "shortDescription": {"text": safe_text(text["short"] or rule_id, 200)},
        "defaultConfiguration": {"level": level},
        "properties": {"tags": _tags(policy, extra), "chock/policy": policy},
    }
    if text["full"]:
        entry["fullDescription"] = {"text": safe_text(text["full"])}
    if uri := _help_uri(extra):
        entry["helpUri"] = uri
    return entry


@dataclass
class GatedPolicy:
    policy: str
    gate: Path
    declared: str
    message: str
    evaluation: runner.Evaluation


def _location(item_path: str, policy: GatedPolicy, repo: Path) -> str:
    """The item's file, else the policy's manifest (code scanning wants every result somewhere)."""
    if item_path:
        return item_path
    manifest = repo / POLICIES_DIR / policy.policy / "manifest.yaml"
    return (manifest if manifest.is_file() else policy.gate).relative_to(repo).as_posix()


def _items(gated: GatedPolicy, repo: Path) -> list[Item]:
    """The findings of a gate that did not allow: the script's own, else one per match line."""
    result = gated.evaluation.result
    if result.findings:
        out = []
        for found in result.findings:
            rule = found.get("rule")
            path = runner._repo_relative(found["path"], repo)
            out.append(Item(rule if isinstance(rule, str) else "", path, found["line"], found["message"], found["key"]))
        return out
    out = []
    for match in result.matches or [result.message or gated.message]:
        first = str(match).splitlines()[0] if str(match).strip() else ""
        parsed = _MATCH.fullmatch(first)
        path = runner._repo_relative(parsed["path"], repo) if parsed else ""
        known = bool(path) and (repo / path).is_file()
        text = parsed["text"] if parsed and known else first
        message = f"{text}: {gated.message}" if gated.message and text != gated.message else text
        out.append(Item("", path if known else "", int(parsed["line"] or 0) if parsed and known else 0, message, first))
    return out


def _fingerprint(policy: str, item: Item, path: str, seen: Counter) -> str:
    base = "\x1f".join([policy, item.rule, path, item.key])
    seen[base] += 1
    return hashlib.sha256(f"{base}\x1f{seen[base]}".encode()).hexdigest()


class _Rules:
    """The log's rules in a stable order, with the index each result points at."""

    def __init__(self, repo: Path, gated: list[GatedPolicy]) -> None:
        self.entries: list[dict] = []
        self.index: dict[str, int] = {}
        for policy in gated:
            level = _LEVEL[policy.declared]
            contract = _contract_rules(repo, policy.policy)
            for rule in contract:
                short, full = str(rule.get("title", "")), str(rule.get("constraint", ""))
                self._add(f"{policy.policy}/{rule['id']}", policy.policy, level, {"short": short, "full": full}, rule)
            if not contract:
                self._add(policy.policy, policy.policy, level, {"short": policy.policy, "full": policy.message}, {})

    def _add(self, rule_id: str, policy: str, level: str, text: dict[str, str], extra: dict) -> None:
        if rule_id not in self.index:
            self.index[rule_id] = len(self.entries)
            self.entries.append(_rule_entry(rule_id, policy, level, text, extra))

    def need(self, rule_id: str, policy: GatedPolicy) -> int:
        """The index of `rule_id`, declared as a bare rule of the policy when the contract does not know it."""
        self._add(rule_id, policy.policy, _LEVEL[policy.declared], {"short": rule_id, "full": policy.message}, {})
        return self.index[rule_id]


def _result(gated: GatedPolicy, item: Item, repo: Path, rules: _Rules, seen: Counter) -> dict:
    evaluation = gated.evaluation
    held = runner._verdict(evaluation.result, gated.declared)
    effective = runner._verdict(evaluation.result, gated.declared, evaluation.level)
    rule_id = f"{gated.policy}/{item.rule}" if item.rule else gated.policy
    path = _location(item.path, gated, repo)
    physical: dict = {"artifactLocation": {"uri": quote(path, safe="/")}}
    if item.line > 0 and item.path:
        physical["region"] = {"startLine": item.line}
    return {
        "ruleId": rule_id,
        "ruleIndex": rules.need(rule_id, gated),
        "level": _LEVEL[held],
        "message": {"text": safe_text(item.message)},
        "locations": [{"physicalLocation": physical}],
        "partialFingerprints": {FINGERPRINT_KEY: _fingerprint(gated.policy, item, path, seen)},
        "properties": {
            "chock/policy": gated.policy,
            "verdict": effective,
            "rolloutHeld": held != effective,
            "rollout": evaluation.level,
        },
    }


def _gate_paths(repo: Path) -> list[Path]:
    return sorted(repo.glob(f"{runner.COMPILED_PREFIX}*/ci-gate/gate.json"))


def _load(repo: Path, gate: Path, base: str, head_ref: str | None) -> tuple[GatedPolicy | None, int | None]:
    """The gate evaluated, or the exit code that says it could not be (a policy id it cannot name is undecided too)."""
    policy = runner._policy_id(gate)
    outcome = runner.evaluate(gate, "ci", None, repo, base=base, head_ref=head_ref)
    if policy is None:
        return None, 2
    if isinstance(outcome, tuple):
        return None, outcome[0] if outcome[1] == runner.VERDICT_ERROR else None
    declared = outcome.spec.get("action", runner.ACTION_BLOCK)
    return GatedPolicy(policy, gate, declared, str(outcome.spec.get("message", "")), outcome), None


def build(repo: Path, base: str, head_ref: str | None = None) -> tuple[dict, int]:
    """The SARIF log of every ci gate's findings, and the exit code the gates reach: 0, 1 (a block) or 2 (undecided)."""
    repo = repo.resolve()
    gated: list[GatedPolicy] = []
    undecided: list[str] = []
    for gate in _gate_paths(repo):
        loaded, error = _load(repo, gate, base, head_ref)
        if loaded:
            gated.append(loaded)
        if error:
            undecided.append(gate.relative_to(repo).as_posix())
    rules = _Rules(repo, gated)
    results, seen, blocked = [], Counter(), False
    for policy in gated:
        evaluation = policy.evaluation
        effective = runner._verdict(evaluation.result, policy.declared, evaluation.level)
        blocked = blocked or effective == runner.ACTION_BLOCK
        if effective != "allow":
            results += [_result(policy, item, repo, rules, seen) for item in _items(policy, repo)]
    results.sort(
        key=lambda r: (
            r["ruleId"],
            r["locations"][0]["physicalLocation"]["artifactLocation"]["uri"],
            r["partialFingerprints"][FINGERPRINT_KEY],
        )
    )
    notes = [{"level": "error", "message": {"text": f"{name} could not be judged"}} for name in undecided]
    log = {
        "$schema": SARIF_SCHEMA,
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "chock",
                        "version": __version__,
                        "informationUri": INFORMATION_URI,
                        "rules": rules.entries,
                    }
                },
                "invocations": [{"executionSuccessful": not undecided, "toolExecutionNotifications": notes}],
                "results": results,
            }
        ],
    }
    return log, 2 if undecided else int(blocked)


def emit(repo: Path, base: str, head_ref: str | None, output: str | None) -> int:
    """Write the SARIF log to `output` (or stdout) and return the gates' exit code."""
    log, code = build(repo, base, head_ref)
    text = json.dumps(log, indent=2, sort_keys=False) + "\n"
    if output:
        Path(output).write_text(text, encoding="utf-8")
        sys.stderr.write(f"sarif: {len(log['runs'][0]['results'])} result(s) written to {output}\n")
    else:
        sys.stdout.write(text)
    return code
