"""The installed content gates a history scan can apply: `content_regex` gates bound to commit.

A gate that judges a diff with a pattern also judges a blob with it, so secrets and invisible
Unicode work on history. Every other kind (a script gate runs vendored code, a ref gate asks
about the repository, a dependency gate about a manifest) is listed as not applied, never
guessed at. The patterns are the installed gate's own, read from `.chock/compiled`.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from chock.gate.runner import GateContext, own_paths
from chock.history.gitlog import HistoryError

COMPILED = (".chock", "compiled")
GATE_FILE = ("git-hook", "gate.json")
KIND = "content_regex"
EVENT = "commit"
RULE_CONTENT = "content-pattern"
RULE_PATH = "forbidden-path"


@dataclass(frozen=True)
class Rule:
    """A gate's patterns as text: the scan runs them in the pattern judge (chock.gate.budget), never in-process."""

    policy: str
    content_pattern: str
    path_pattern: str | None
    pragma_pattern: str | None
    judge: GateContext

    def covers(self, path: str) -> bool:
        return self.judge.in_scope(path)


def _checked(policy: str, pattern: object) -> str | None:
    """`pattern` as text once it is known to compile; None for none."""
    if not pattern:
        return None
    try:
        re.compile(str(pattern))
    except re.error as exc:
        raise HistoryError(f"{policy}: gate pattern does not compile ({exc}); refusing to scan without it") from exc
    return str(pattern)


def _rule(repo: Path, gate_path: Path, spec: dict) -> Rule:
    policy = gate_path.parents[1].name
    params = spec.get("params") or {}
    content = _checked(policy, params.get("content_pattern"))
    if content is None:
        raise HistoryError(f"{policy}: content_regex gate has no content_pattern; refusing to scan without it")
    judge = GateContext(repo_root=repo, scope=spec.get("paths"), own=own_paths(gate_path))
    return Rule(
        policy,
        content,
        _checked(policy, params.get("forbidden_path_regex")),
        _checked(policy, params.get("allowlist_pragma")),
        judge,
    )


def _same(one: Rule, other: Rule) -> bool:
    shape = ("policy", "content_pattern", "path_pattern", "pragma_pattern")
    same = all(getattr(one, key) == getattr(other, key) for key in shape)
    return same and (one.judge.scope, one.judge.own) == (other.judge.scope, other.judge.own)


def load_rules(repo: Path, surfaces: tuple[str, ...] = (GATE_FILE[0],)) -> tuple[list[Rule], list[str]]:
    """(applicable rules, ids of installed commit gates this scan cannot apply), both in policy order.

    `surfaces` are the compiled surfaces read (the git-hook one by default); a rule two surfaces share is kept once.
    """
    root = repo.joinpath(*COMPILED)
    found = (
        {path for surface in surfaces for path in root.glob(f"*/{surface}/{GATE_FILE[1]}")} if root.is_dir() else set()
    )
    gates = sorted(found)
    rules: list[Rule] = []
    skipped: list[str] = []
    for gate_path in gates:
        try:
            spec = json.loads(gate_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise HistoryError(f"cannot read installed gate {gate_path.parents[1].name}: {exc}") from exc
        name = gate_path.parents[1].name
        if not isinstance(spec, dict) or not isinstance(spec.get("on", []), list):
            raise HistoryError(f"installed gate {name} is not a gate document; refusing to skip it silently")
        if EVENT not in spec.get("on", []):
            continue
        if spec.get("kind") == KIND:
            rule = _rule(repo, gate_path, spec)
            if not any(_same(rule, kept) for kept in rules):
                rules.append(rule)
        elif name not in skipped:
            skipped.append(gate_path.parents[1].name)
    if not rules:
        raise HistoryError("no installed content gates found under .chock/compiled; run `chock sync` first")
    return rules, skipped
