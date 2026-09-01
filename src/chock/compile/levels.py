"""The enforcement-level vocabulary, its strength order, and how a level is derived."""

from __future__ import annotations

from typing import Iterable, NamedTuple

from agentseam import contract as _contract
from agentseam import matrix as _matrix
from agentseam import matrix_terms as _terms

from chock import evidence

MATRIX_AGENT = {
    "claude": "claude_code",
    "cursor": "cursor",
    "copilot": "vscode_copilot",
    "vscode": "vscode_copilot",
}


def _matrix_can_block(chock_agent: str) -> bool:
    """Whether agentseam's verified matrix confirms `chock_agent` can block a pre-tool call."""
    mapped = MATRIX_AGENT.get(chock_agent)
    return bool(mapped) and _matrix.can_block(mapped, _contract.PRE_TOOL)


DISABLED = "disabled"


DEGRADES_TO_ALLOW = "allow"
DEGRADES_TO_ASK = "ask"
DEGRADES_TO_DENY = "deny"
DEGRADATION_MODES = (DEGRADES_TO_ALLOW, DEGRADES_TO_ASK, DEGRADES_TO_DENY)


CONTROL_DEGRADES_TO = DEGRADES_TO_ALLOW


IN_AGENT_LEVELS = ("none", "detect", "best-effort", "fail-to-ask", "enforceable", "enforced")

UNRANKED_LEVELS = ("enforced-at-commit", "advisory", DISABLED)

UNREPORTABLE_LEVELS = ("detect",)

COVERAGE_LEVELS = (
    *(level for level in IN_AGENT_LEVELS if level not in UNREPORTABLE_LEVELS),
    *UNRANKED_LEVELS,
)


def level_rank(level: str) -> int:
    """Position of `level` in the in-agent strength ladder; higher is stronger."""
    try:
        return IN_AGENT_LEVELS.index(level)
    except ValueError:
        raise ValueError(
            f"{level!r} has no rank on the in-agent ladder {IN_AGENT_LEVELS}; "
            f"{UNRANKED_LEVELS} describe different mechanisms and are deliberately unranked"
        ) from None


BASIS_CAP = {
    _terms.BASIS_LIVE: "enforced",
    _terms.BASIS_LIVE_PARTIAL: "enforceable",
    _terms.BASIS_SOURCE: "best-effort",
    _terms.BASIS_DOCS: "best-effort",
    _terms.BASIS_THIRD_PARTY: "best-effort",
    _terms.BASIS_INHERITED: "detect",
}


class Grade(NamedTuple):
    """One coverage cell: the word, the evidence binding it, and whether chock saw it work."""

    level: str
    basis: str | None
    witnessed: bool


def cap_for(basis: str) -> str:
    """The strongest word this KIND of evidence can back."""
    try:
        return BASIS_CAP[basis]
    except KeyError:
        raise ValueError(
            f"no cap recorded for basis {basis!r}; a new evidence kind must be given a ceiling "
            f"before a grade may rest on it, not default to the strongest word"
        ) from None


def weakest_basis(bases: Iterable[str]) -> str | None:
    """The basis whose cap is lowest -- the one that binds. None when nothing rests on evidence."""
    ranked = sorted(bases, key=lambda basis: level_rank(cap_for(basis)))
    return ranked[0] if ranked else None


def capped(level: str, bases: Iterable[str]) -> str:
    """`level`, lowered to what the weakest basis under it can back; unreportable becomes `none`."""
    binding = weakest_basis(bases)
    if binding is not None and level in IN_AGENT_LEVELS:
        level = min(level, cap_for(binding), key=level_rank)
    return "none" if level in UNREPORTABLE_LEVELS else level


def resting_bases(mapped: str) -> tuple[str, ...]:
    """Every evidence basis an in-agent grade for matrix agent `mapped` rests on.

    Today that is the matrix row alone: the wire claims chock's hooks consume are still
    hand-written here rather than carried with their own evidence, so there is nothing
    honest to add. agentseam's per-claim vendor entries join this tuple when they land.
    """
    return (_matrix.basis(mapped),)


def in_agent_level(agent: str, *, degrades_to: str = CONTROL_DEGRADES_TO) -> str:
    """The honest word for an INSTALLED in-agent pre-execution control on `agent`."""
    if degrades_to not in DEGRADATION_MODES:
        raise ValueError(f"unknown degradation mode {degrades_to!r}; expected one of {DEGRADATION_MODES}")
    mapped = MATRIX_AGENT.get(agent)
    if not mapped:
        return "none"
    host = _matrix.enforcement_level(mapped, _contract.PRE_TOOL)
    lifts = host == "best-effort" and degrades_to != DEGRADES_TO_ALLOW and evidence.honours_ask(mapped)
    return capped("fail-to-ask" if lifts else host, resting_bases(mapped))


def in_agent_grade(agent: str, surface: str, *, degrades_to: str = CONTROL_DEGRADES_TO) -> Grade:
    """`in_agent_level` with the evidence that bounds it and chock's own witness for `surface`."""
    mapped = MATRIX_AGENT.get(agent)
    if not mapped:
        return Grade("none", None, False)
    return Grade(
        in_agent_level(agent, degrades_to=degrades_to),
        weakest_basis(resting_bases(mapped)),
        evidence.witness(mapped, surface) is not None,
    )


def render_grade(grade: Grade) -> str:
    """One cell as a report prints it -- `best-effort (vendor-docs)`, evidence never detached."""
    return f"{grade.level} ({grade.basis})" if grade.basis else grade.level
