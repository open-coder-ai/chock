"""AMB-2: deterministic contradiction detection over the compiled ambient rule surface.

Arbiter (arXiv:2603.08993) finds that the agent resolving instruction conflicts cannot be
the agent detecting them -- detection needs a different vantage point. So this module never
calls a model: it does set arithmetic over `.agents/policies/INDEX.md`, the surface
`check_ambient_token_budget()` (AMB-1) already measures, using only regex and frozensets.
See `chock/plan/rule-conflict-detection.md` in org-plan and `docs/authoring-policies.md`.
"""

from __future__ import annotations

import argparse
from itertools import combinations
from pathlib import Path

from chock.validation.ambient_parser import (
    Clause,
    expand_scope_clauses,
    find_overrides,
    iter_rule_lines,
    parse_clauses,
)
from chock.validation.report import Finding, Report, emit

#: The closed modality vocabulary this catalog actually emits (see the brief's derivation:
#: `never`/`block` occur as prohibiting verbs, `prefer`/`require_approval` as permissive
#: ones, in .agents/policies/*/manifest.yaml). Two verbs from opposite sides are the only
#: pairing this check treats as an opposing verdict for the same subject.
_PROHIBIT = frozenset({"never", "block"})
_PERMIT = frozenset({"prefer", "require_approval"})


def _token_estimate(text: str) -> int:
    """Same chars/4 estimator AMB-1 (`check_ambient_token_budget`) uses, for cost messages."""
    return max(0, len(text) // 4)


def _opposes(verb_a: str, verb_b: str) -> bool:
    return (verb_a in _PROHIBIT and verb_b in _PERMIT) or (verb_a in _PERMIT and verb_b in _PROHIBIT)


def _finding(index_path: Path, key: str, a: Clause, b: Clause, classified: tuple[str, str]) -> Finding:
    kind, note = classified
    left, right = (a, b) if (a.policy_id, a.line) <= (b.policy_id, b.line) else (b, a)
    message = (
        f"'{key}': policy '{left.policy_id}' (line {left.line}) says `{left.raw}`, "
        f"policy '{right.policy_id}' (line {right.line}) says `{right.raw}`. {note} "
        f"Add `# chock: conflict-reviewed {key}` to one policy's rule.text to accept this."
    )
    return Finding(str(index_path), kind, "error", message)


def _classify(a: Clause, b: Clause) -> tuple[str, str] | None:
    """Return (kind, note) for a conflicting pair sharing subject `key`, or None to skip it.

    Same-verb pairs are never flagged here: `never(commit): secrets` and `never(commit):
    --no-verify` both just extend the same subject's forbidden-target list -- that is
    additive, not contradictory (`verb(subject): targets` is a set the verb applies to, not
    a single-valued assignment). A real conflict needs two *opposing* verbs for the same
    subject, from the closed vocabulary this catalog actually emits.
    """
    if a.verb == b.verb or not _opposes(a.verb, b.verb):
        return None
    if a.scope or b.scope:
        return "scope_overlap", "Both target this path with opposing verdicts."
    if not a.targets and not b.targets:
        return "modality_conflict", "Opposing verbs from the closed vocabulary for the same subject."
    return "direct_contradiction", "Opposing verbs from the closed vocabulary naming incompatible values."


def _same_key_findings(index_path: Path, clauses: list[Clause], overrides: dict[str, set[str]]) -> list[Finding]:
    by_key: dict[str, list[Clause]] = {}
    for clause in clauses:
        for subject in clause.subjects:
            by_key.setdefault(subject, []).append(clause)

    findings: list[Finding] = []
    seen: set[tuple[str, int, str, int]] = set()
    for key, group in by_key.items():
        for a, b in combinations(group, 2):
            if a.policy_id == b.policy_id:
                continue
            pair_id = tuple(sorted([(a.policy_id, a.line), (b.policy_id, b.line)]))
            dedupe_key = (*pair_id[0], *pair_id[1])
            if dedupe_key in seen:
                continue
            classified = _classify(a, b)
            if classified is None:
                continue
            if key in overrides.get(a.policy_id, set()) or key in overrides.get(b.policy_id, set()):
                continue
            findings.append(_finding(index_path, key, a, b, classified))
            seen.add(dedupe_key)
    return findings


def _redundancy_findings(index_path: Path, clauses: list[Clause], overrides: dict[str, set[str]]) -> list[Finding]:
    findings: list[Finding] = []
    for a, b in combinations(clauses, 2):
        if a.policy_id == b.policy_id or a.verb != b.verb:
            continue
        if a.subjects != b.subjects or not a.targets or not b.targets:
            continue
        if a.targets != b.targets and not (a.targets < b.targets or b.targets < a.targets):
            continue
        key = "|".join(a.subjects) or a.verb
        if key in overrides.get(a.policy_id, set()) or key in overrides.get(b.policy_id, set()):
            continue
        left, right = (a, b) if (a.policy_id, a.line) <= (b.policy_id, b.line) else (b, a)
        relation = "duplicates" if a.targets == b.targets else "is subsumed by"
        cost = _token_estimate(right.raw)
        message = (
            f"'{key}': policy '{right.policy_id}' (line {right.line}) {relation} "
            f"policy '{left.policy_id}' (line {left.line}): `{right.raw}` vs `{left.raw}` "
            f"(~{cost} redundant tokens against the AMB-1 budget). "
            f"Add `# chock: conflict-reviewed {key}` to one policy's rule.text to accept this."
        )
        findings.append(Finding(str(index_path), "redundancy", "warning", message))
    return findings


def check_ambient_conflicts(root: Path, report: Report) -> None:
    """AMB-2: contradictions between rules compiled from independently authored policies.

    Reads only `.agents/policies/INDEX.md` -- the surface AMB-1 already measures -- and does
    nothing but regex parsing and frozenset arithmetic. No model call.
    """
    index_path = root / ".agents" / "policies" / "INDEX.md"
    if not index_path.exists():
        return
    lines = iter_rule_lines(index_path.read_text(encoding="utf-8"))
    if not lines:
        return

    clauses = parse_clauses(lines)
    scope_clauses = expand_scope_clauses(clauses)
    overrides = find_overrides(lines)

    for finding in _same_key_findings(index_path, clauses + scope_clauses, overrides):
        report.add(finding)
    for finding in _redundancy_findings(index_path, clauses, overrides):
        report.add(finding)


def main(argv: list[str] | None = None) -> int:
    """`chock check --only conflicts`: report every side of every ambient-rule conflict."""
    parser = argparse.ArgumentParser(prog="chock check --only conflicts")
    parser.add_argument("--repo", default=".", help="Repo root")
    parser.add_argument("--json", action="store_true", help="Emit JSON report")
    args = parser.parse_args(argv)

    report = Report()
    check_ambient_conflicts(Path(args.repo).resolve(), report)
    emit(report, use_json=args.json)
    return 0 if report.is_clean() else 1
