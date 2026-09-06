"""Export chock policies to context-report's run/v0.1 case-directory format.

The format is documented at `spec/run/v0.1/README.md` in `open-coder-ai/context-report`; this
module writes it, chock never imports context-report. A tier-3 case (no `execute` block in
`evals/suite.yaml`) has no executable form to replay, so an ambient rule's effect on agent
behaviour is the only thing left to measure -- see `docs/evals.md` and `chock.eval.model.Case`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from chock.compile.emitters.advisory import advisory_lines
from chock.emit import write_generated, write_generated_json
from chock.eval.suites import Policy, discover_policies

_SUITE_RELPATH = Path("evals") / "suite.yaml"
_SUBJECTS_DIRNAME = "subjects"
_EVALS_DIRNAME = "evals"
_GRADERS_DIRNAME = "graders"
_RUN_MANIFEST_VERSION = "v0.1"

WRONG_SHAPE = (
    "{suite} has no top-level `suite:` key (found {keys}) -- it does not match the "
    "`suite.cases[]` shape this exporter reads, so it cannot say whether any case is tier-3"
)
NO_TIER3_CASES = "policy {policy_id!r} skipped: no tier-3 cases (every case in {suite} declares an `execute` block)"
NO_RULE_TEXT = "policy {policy_id!r} skipped: no rule.text in {manifest} to measure"
NOT_FOUND = "policy {policy_id!r} not found under {repo_root}"

_SLUG_WORDS = 6
_SLUG_CHARS = 48
_WORD = re.compile(r"[a-z0-9]+")
_UNSAFE_PATH_CHARS = re.compile(r"[^A-Za-z0-9._-]+")
# context-report's own block extractor strips markdown emphasis/code characters (its
# `_INLINE_FORMATTING`) before computing a rule's id -- e.g. "without_approval" becomes
# "withoutapproval", not two words. Mirrored here (chock does not import context-report) so
# the id this module puts in a `rule:<id>` tag matches the one context-report derives from
# the same rendered text; `tests/test_context_report_export.py` pins the parity with a fixture.
_MARKDOWN_EMPHASIS = re.compile(r"[*_`]")


class SuiteShapeError(ValueError):
    """A policy's `evals/suite.yaml` is not in the `suite: {cases: [...]}` shape this exporter reads."""


@dataclass(frozen=True)
class Tier3Case:
    """One eval case with no `execute` block, as read for export -- chock's own name (tier 3)."""

    id: str
    prompt: str
    expect: str


@dataclass
class ExportResult:
    """What `export()` did, so the CLI can print it and choose an exit code."""

    exported: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def slug(text: str) -> str:
    """A rule id derived from a rule's own text, matching context-report run spec v0.1.

    Per `spec/run/v0.1/README.md#tasks` ("Rule ids"): lowercase the text, take the runs of
    `[a-z0-9]+` in order, keep the first 6 words, join with `-`, truncate to 48 characters,
    and strip a trailing `-`; an empty result is `rule`. Implemented independently here (chock
    does not depend on context-report) so the two stay in lockstep only by both following the
    spec, not by sharing code.
    """
    words = _WORD.findall(text.lower())[:_SLUG_WORDS]
    return "-".join(words)[:_SLUG_CHARS].rstrip("-") or "rule"


def rendered_rule_id(lines: list[str]) -> str:
    """The rule id for a subject's rendered text, as context-report's extractor would derive it.

    context-report strips markdown emphasis/code characters before deriving the id (see
    `_MARKDOWN_EMPHASIS` above); this must run before `slug()` for the two tools to agree.
    """
    return slug(_MARKDOWN_EMPHASIS.sub("", "\n".join(lines)))


def path_slug(text: str) -> str:
    """A filesystem-safe fragment for a case directory name: anything outside `[A-Za-z0-9._-]` becomes `-`."""
    return _UNSAFE_PATH_CHARS.sub("-", text).strip("-") or "case"


def _read_yaml(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def tier3_cases(policy: Policy) -> list[Tier3Case]:
    """Cases from `evals/suite.yaml` with no `execute` block.

    Raises `SuiteShapeError` for the older `eval_suite:`/`test_cases:` shape a few policies still
    ship (`minimal-content`, `yagni` as of chock@4743bd0): that shape has no `execute` concept at
    all, so reading it as "zero tier-3 cases" would be a false negative, not a true one.
    """
    suite_path = policy.dir / _SUITE_RELPATH
    raw = _read_yaml(suite_path)
    if "suite" not in raw:
        raise SuiteShapeError(WRONG_SHAPE.format(suite=suite_path, keys=sorted(raw)))
    suite = raw["suite"] or {}
    return [
        Tier3Case(id=str(c["id"]), prompt=str(c["prompt"]), expect=str(c.get("expect", "")))
        for c in suite.get("cases") or []
        if isinstance(c, dict) and "execute" not in c
    ]


def rule_lines(policy: Policy, repo_root: Path) -> list[str]:
    """The <=2 lines chock actually renders for this policy into an agent's context.

    Delegates to `chock.compile.emitters.advisory.advisory_lines` -- the same function the
    ambient/plugin emitters use -- rather than re-deriving the rendering here.
    """
    return advisory_lines(policy.dir, policy.manifest, repo_root)


def render_subject(policy_id: str, lines: list[str]) -> str:
    """The subject file body: a heading (dropped by context-report's block extractor as a
    break) followed by the rule text as one block, unchanged."""
    body = "\n".join(lines)
    return f"# {policy_id}\n\n{body}\n"


def _frontmatter(data: dict[str, Any], body: str) -> str:
    return "---\n" + yaml.safe_dump(data, sort_keys=False) + "---\n" + body.rstrip() + "\n"


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    write_generated(path, text)


def _write_case(evals_dir: Path, policy_id: str, case: Tier3Case, rule_id: str) -> None:
    case_dir = evals_dir / f"{path_slug(policy_id)}--{path_slug(case.id)}"
    prompt = _frontmatter(
        {"plugins": [f"../../{_SUBJECTS_DIRNAME}/{policy_id}.md"], "tags": [f"rule:{rule_id}"]},
        case.prompt,
    )
    _write(case_dir / "prompt.md", prompt)
    grader = _frontmatter(
        {"type": "llm", "rule": rule_id, "criteria": case.expect},
        f"Compliance for chock policy `{policy_id}` eval case `{case.id}`.",
    )
    _write(case_dir / _GRADERS_DIRNAME / "expect.md", grader)


def _export_one(policy: Policy, repo_root: Path, out_dir: Path) -> str | None:
    """Export one policy; return the skip notice if it had nothing to export, else None."""
    cases = tier3_cases(policy)
    if not cases:
        return NO_TIER3_CASES.format(policy_id=policy.id, suite=policy.dir / _SUITE_RELPATH)
    lines = rule_lines(policy, repo_root)
    if not lines:
        return NO_RULE_TEXT.format(policy_id=policy.id, manifest=policy.dir / "manifest.yaml")

    rule_id = rendered_rule_id(lines)
    _write(out_dir / _SUBJECTS_DIRNAME / f"{policy.id}.md", render_subject(policy.id, lines))
    for case in cases:
        _write_case(out_dir / _EVALS_DIRNAME, policy.id, case, rule_id)
    return None


def _run_manifest(exported: list[str]) -> dict[str, Any]:
    return {
        "contextReportRun": _RUN_MANIFEST_VERSION,
        "subjects": [
            {"id": pid, "path": f"{_SUBJECTS_DIRNAME}/{pid}.md", "kind": "instruction-file"} for pid in exported
        ],
        "target": {"name": "claude_code"},
        "models": [],
        "tasks": _EVALS_DIRNAME,
        "arms": {"nPerArm": 2, "seed": 1, "mode": "isolated"},
        "judge": None,
        "out": "out",
    }


_README = """\
# context-report export

Chock policies exported to context-report's run/v0.1 format (tier-3 eval cases -- the ones with
no `execute` block, where only agent behaviour under the ambient rule can be measured).

Before running:

1. Fill in `models` in `run.json` with the subject model(s) to ablate, e.g.
   `{"provider": "anthropic", "id": "claude-sonnet-5"}`.
2. Optionally set `judge` to a model reference to grade the `llm` graders under `evals/`.
3. `context-report run run.json`

See context-report's `spec/run/v0.1/README.md` for the manifest fields.
"""


def export(repo_root: Path, out_dir: Path, policy_ids: list[str] | None = None) -> ExportResult:
    """Export every selected policy with tier-3 cases; skip or error on the rest (never a silent zero)."""
    result = ExportResult()
    policies = _resolve(repo_root, policy_ids, result)
    for policy in policies:
        try:
            notice = _export_one(policy, repo_root, out_dir)
        except SuiteShapeError as exc:
            result.errors.append(f"{policy.id}: {exc}")
            continue
        if notice is not None:
            result.skipped.append(notice)
        else:
            result.exported.append(policy.id)
    if result.exported:
        write_generated_json(out_dir / "run.json", _run_manifest(result.exported))
        write_generated(out_dir / "README.md", _README)
    return result


def _is_policy(policy: Policy) -> bool:
    """`discover_policies` also returns skills (`.agents/skills/<id>`); this exporter is policies only."""
    return policy.dir.parent.name == "policies"


def _resolve(repo_root: Path, policy_ids: list[str] | None, result: ExportResult) -> list[Policy]:
    """Every policy in the repo (default), or exactly the named ones -- an unknown id is an error."""
    if not policy_ids:
        return [p for p in discover_policies(repo_root) if _is_policy(p)]
    policies: list[Policy] = []
    for pid in policy_ids:
        found = [p for p in discover_policies(repo_root, pid) if _is_policy(p)]
        if found:
            policies.append(found[0])
        else:
            result.errors.append(NOT_FOUND.format(policy_id=pid, repo_root=repo_root))
    return policies
