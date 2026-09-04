"""Parse the compiled ambient rule surface with provenance, for AMB-2.

AMB-1 established that the surface an agent actually reads is `.agents/policies/INDEX.md`
(not an inlined block in `AGENTS.md`, and not `rule.text` -- `chock sync` may reformat,
demote advise-tier entries to INDEX-extended.md, or drop them under budget pressure). This
parses that rendered file, one physical line at a time, and keeps the policy id and line
number for every directive so a conflict finding can name both sides.

The DSL is `verb(subject_a|subject_b): target_a|target_b`, optionally missing the subject
parens or the target, clauses separated by `;`, comments introduced by `#`. This is a
structural parser only: unmatched text is dropped, never guessed at (`checks_conflicts.py`
prefers a missed finding over an invented one).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_ENTRY_RE = re.compile(r"^-\s+\*\*([a-z][a-z0-9-]*)\*\*:\s*(.*)$")
_CONTINUATION_RE = re.compile(r"^ {2}(.+)$")
_SECTION_RE = re.compile(r"^## ")
_RULES_HEADER = "## Rules — always apply"

_CLAUSE_RE = re.compile(r"^(?P<verb>[a-z][a-z0-9_]*)(?:\((?P<subject>[^)]*)\))?(?:\s*:\s*(?P<target>.+))?$")
_NESTED_CALL_RE = re.compile(r"^(?P<verb>[a-z][a-z0-9_]*)\((?P<subject>[^)]*)\)$")
_OVERRIDE_RE = re.compile(r"#\s*chock:\s*conflict-reviewed\s+([\w.\-,\s]+)")
_LIST_SPLIT_RE = re.compile(r"[|,]")
_TOKEN_SPLIT_RE = re.compile(r"[|+,]")


@dataclass(frozen=True)
class RuleLine:
    """One physical line of one policy's rule text, as emitted in INDEX.md."""

    policy_id: str
    line: int
    text: str


@dataclass(frozen=True)
class Clause:
    """One deterministically parsed directive: `verb(subject): target`."""

    policy_id: str
    line: int
    verb: str
    subjects: tuple[str, ...]
    targets: frozenset[str]
    raw: str
    scope: bool = False


def _tokens(text: str, pattern: re.Pattern[str]) -> tuple[str, ...]:
    return tuple(t for t in (piece.strip().lower() for piece in pattern.split(text)) if t)


def iter_rule_lines(index_text: str) -> list[RuleLine]:
    """Every physical rule line under '## Rules -- always apply', with its 1-based line number."""
    current_id: str | None = None
    in_rules = False
    out: list[RuleLine] = []
    for lineno, raw in enumerate(index_text.splitlines(), start=1):
        if raw.strip() == _RULES_HEADER:
            in_rules = True
            continue
        if not in_rules:
            continue
        if _SECTION_RE.match(raw):
            break
        entry = _ENTRY_RE.match(raw)
        if entry:
            current_id, rest = entry.group(1), entry.group(2)
            if rest:
                out.append(RuleLine(current_id, lineno, rest))
                current_id = None
            continue
        continuation = _CONTINUATION_RE.match(raw) if current_id else None
        if continuation:
            out.append(RuleLine(current_id, lineno, continuation.group(1)))
    return out


def parse_clauses(lines: list[RuleLine]) -> list[Clause]:
    """Split each rule line on ';' into directive clauses; unrecognised text is dropped."""
    clauses: list[Clause] = []
    for rule_line in lines:
        body = rule_line.text.split("#", 1)[0]
        for raw_piece in body.split(";"):
            piece = raw_piece.strip()
            if not piece:
                continue
            match = _CLAUSE_RE.match(piece)
            if not match:
                continue
            subject_text = match.group("subject")
            target_text = match.group("target")
            clauses.append(
                Clause(
                    policy_id=rule_line.policy_id,
                    line=rule_line.line,
                    verb=match.group("verb").lower(),
                    subjects=_tokens(subject_text, _LIST_SPLIT_RE) if subject_text else (),
                    targets=frozenset(_tokens(target_text, _TOKEN_SPLIT_RE)) if target_text else frozenset(),
                    raw=piece,
                )
            )
    return clauses


def _nested_targets(clause: Clause) -> tuple[str, frozenset[str]] | None:
    """If the whole target is itself a `verb(subject)` call, return (verb, subject tokens)."""
    if not clause.targets or len(clause.targets) != 1:
        return None
    (only_target,) = clause.targets
    match = _NESTED_CALL_RE.match(only_target)
    if not match:
        return None
    return match.group("verb"), frozenset(_tokens(match.group("subject"), _LIST_SPLIT_RE))


def expand_scope_clauses(clauses: list[Clause]) -> list[Clause]:
    """Flatten `outer(paths): verb(targets)` into per-path synthetic clauses.

    `agent_config(AGENTS.md|.claude/settings): never(hand_edit)` becomes one synthetic
    clause per path, each carrying the nested verb -- so a scope-overlap finding (a path
    named by two policies with opposing verdicts) falls out of the same same-key grouping
    used for direct contradictions and modality conflicts, instead of a bespoke algorithm.
    """
    expanded: list[Clause] = []
    for clause in clauses:
        if not clause.subjects:
            continue
        nested = _nested_targets(clause)
        if nested is None:
            continue
        nested_verb, nested_targets = nested
        for subject in clause.subjects:
            expanded.append(
                Clause(
                    policy_id=clause.policy_id,
                    line=clause.line,
                    verb=nested_verb,
                    subjects=(subject,),
                    targets=nested_targets,
                    raw=clause.raw,
                    scope=True,
                )
            )
    return expanded


def find_overrides(lines: list[RuleLine]) -> dict[str, set[str]]:
    """`# chock: conflict-reviewed <key>[, <key>...]` per policy, from the unstripped line text."""
    overrides: dict[str, set[str]] = {}
    for rule_line in lines:
        match = _OVERRIDE_RE.search(rule_line.text)
        if not match:
            continue
        keys = {k.strip() for k in re.split(r"[,\s]+", match.group(1)) if k.strip()}
        overrides.setdefault(rule_line.policy_id, set()).update(keys)
    return overrides
