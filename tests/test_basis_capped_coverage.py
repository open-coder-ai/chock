"""Basis-capped grading: what evidence may back, and what it may never let in."""

from __future__ import annotations

import pytest
from agentseam import contract as _contract
from agentseam import matrix as _matrix

from chock import evidence
from chock.compile import levels
from chock.compile.levels import (
    BASIS_CAP,
    CONTROL_DEGRADES_TO,
    DEGRADES_TO_ASK,
    IN_AGENT_LEVELS,
    IN_AGENT_TODAY,
    cap_for,
    capped,
    in_agent_grade,
    in_agent_level,
    level_rank,
    render_grade,
    resting_bases,
    weakest_basis,
)
from chock.compile.surfaces import SURFACE_AGENTS, Surface
from chock.vendors import CHOCK_AGENT

# The in-agent alias view of the one unified table (chock.vendors.CHOCK_AGENT, scoped
# by IN_AGENT_TODAY) -- read-only here; patch IN_AGENT_TODAY/CHOCK_AGENT, not this.
MATRIX_AGENT = {a: CHOCK_AGENT[a] for a in IN_AGENT_TODAY}

WEAKEST_FIRST = tuple(sorted(_matrix.BASES, key=lambda basis: level_rank(cap_for(basis))))


def test_every_basis_upstream_publishes_has_a_ceiling_here() -> None:
    """A new upstream evidence kind must be given a cap deliberately, not inherit the top of the ladder."""
    assert set(BASIS_CAP) == set(_matrix.BASES)

    with pytest.raises(ValueError):
        cap_for("hearsay")


def test_the_anchor_the_owner_fixed_holds() -> None:
    """Documentation is a claim about what a vendor SAYS; it can never back `enforced`."""
    assert cap_for(_matrix.BASIS_LIVE) == "enforced"
    assert cap_for("vendor-docs") == "best-effort"
    assert capped("enforced", ["vendor-docs"]) == "best-effort"


def test_an_inherited_basis_is_unreportable_rather_than_downgraded() -> None:
    """`detect` is not a verdict coverage.json may carry, so a grade capped there surfaces as none."""
    assert cap_for(_matrix.BASIS_INHERITED) == "detect"
    assert capped("enforced", [_matrix.BASIS_INHERITED]) == "none"


def test_the_weakest_claim_binds_not_the_strongest() -> None:
    """One weak claim caps the cell even when everything else it rests on was live-run."""
    assert weakest_basis([_matrix.BASIS_LIVE, "vendor-docs"]) == "vendor-docs"
    assert capped("enforced", [_matrix.BASIS_LIVE, "vendor-docs"]) == "best-effort"
    assert weakest_basis([]) is None
    assert capped("enforced", []) == "enforced"


@pytest.mark.parametrize("level", IN_AGENT_LEVELS)
def test_weakening_a_basis_never_raises_a_grade(level: str) -> None:
    """Test (e), monotonicity: walk every basis weakest-first; the grade may only fall."""
    grades = [capped(level, [basis]) for basis in WEAKEST_FIRST]
    ranks = [level_rank(grade) for grade in grades]

    assert ranks == sorted(ranks), (
        f"{level}: weakening the evidence raised the grade: {list(zip(WEAKEST_FIRST, grades))}"
    )


def test_crossing_a_cap_boundary_actually_drops_the_grade() -> None:
    """Monotonicity alone is satisfied by a cap that never bites, so pin one that does."""
    assert capped("enforced", [_matrix.BASIS_LIVE]) == "enforced"
    assert capped("enforced", [_matrix.BASIS_LIVE_PARTIAL]) == "enforceable"
    assert capped("enforced", ["third-party-install"]) == "best-effort"


@pytest.mark.parametrize("basis", _matrix.BASES)
def test_evidence_can_never_add_capability_the_matrix_denies(basis: str, monkeypatch) -> None:
    """Test (c): the strongest possible evidence under a row that cannot block still grades none."""
    unable = next(a for a in _matrix.agents() if not _matrix.can_block(a, _contract.PRE_TOOL))
    assert _matrix.enforcement_level(unable, _contract.PRE_TOOL) in ("none", "detect")
    assert capped(_matrix.enforcement_level(unable, _contract.PRE_TOOL), [basis]) == "none"

    monkeypatch.setattr(levels, "IN_AGENT_TODAY", (*levels.IN_AGENT_TODAY, "synthetic"))
    monkeypatch.setitem(CHOCK_AGENT, "synthetic", unable)
    monkeypatch.setattr(levels, "resting_bases", lambda _mapped: (basis,))
    claiming = evidence.parse_claims(
        [
            {
                "agent": unable,
                "claim": "honours_ask",
                "verdict": "ask",
                "honours": True,
                "evidence": "tested",
                "test": "t.py::t",
            }
        ]
    )
    monkeypatch.setattr(evidence, "honours_ask", lambda agent, table=None: agent in {c.agent for c in claiming})

    assert in_agent_level("synthetic", degrades_to=DEGRADES_TO_ASK) == "none"


def test_the_fail_to_ask_lift_needs_a_tested_claim(monkeypatch) -> None:
    """Documented-only never earns the lift; the claim must be one our suite actually exercises."""
    fail_open = [a for a in sorted(SURFACE_AGENTS) if in_agent_level(a) == "best-effort"]
    assert fail_open, "no fail-open agent left to test the lift on"

    for agent in fail_open:
        assert in_agent_level(agent, degrades_to=DEGRADES_TO_ASK) == "fail-to-ask"

    monkeypatch.setattr(evidence, "honours_ask", lambda agent, table=None: False)
    for agent in fail_open:
        assert in_agent_level(agent, degrades_to=DEGRADES_TO_ASK) == "best-effort", (
            f"{agent} was lifted on a claim nothing tests"
        )


def test_a_deny_degrading_host_never_earns_the_lift() -> None:
    """Codex rejects the prompt outright, so its recorded claim must keep it off the rung."""
    codex = evidence.claim("codex_cli", evidence.HONOURS_ASK)

    assert codex is not None and codex.verdict == evidence.WIRE_DENY and not codex.honours
    assert not evidence.honours_ask("codex_cli")


def test_the_in_agent_set_is_the_matrix_predicate_recomputed() -> None:
    """Test (a): membership is `can_block`, recomputed here rather than read from the same list."""
    derived = {
        agent
        for agent, mapped in MATRIX_AGENT.items()
        if agent in SURFACE_AGENTS and _matrix.can_block(mapped, _contract.PRE_TOOL)
    }
    declared = {a for a, s in SURFACE_AGENTS.items() if s & {Surface.PRE_TOOL_USE, Surface.AGENT_HOOKS}}

    assert derived == declared
    assert not {a for a in SURFACE_AGENTS if a not in MATRIX_AGENT} & declared


@pytest.mark.parametrize("agent", sorted(MATRIX_AGENT))
def test_every_in_agent_grade_carries_the_evidence_that_bounds_it(agent: str) -> None:
    """A word without its basis is the overclaim the cell shape exists to prevent."""
    surface = Surface.AGENT_HOOKS.value if agent in ("copilot", "vscode") else Surface.PRE_TOOL_USE.value
    grade = in_agent_grade(agent, surface)

    assert grade.basis in _matrix.BASES
    assert grade.basis == weakest_basis(resting_bases(MATRIX_AGENT[agent]))
    assert level_rank(grade.level) <= level_rank(cap_for(grade.basis))
    assert render_grade(grade) == f"{grade.level} ({grade.basis})"
    assert grade.witnessed is (evidence.witness(MATRIX_AGENT[agent], surface) is not None)


def test_todays_words_all_clear_their_cap() -> None:
    """The day-one claim of the design: capping changes cells, not words. Recomputed, not asserted."""
    for agent in sorted(MATRIX_AGENT):
        mapped = MATRIX_AGENT[agent]
        uncapped = _matrix.enforcement_level(mapped, _contract.PRE_TOOL)

        assert in_agent_level(agent, degrades_to=CONTROL_DEGRADES_TO) == uncapped, (
            f"{agent}: the basis cap moved a day-one word; that is a finding, not a silent ship"
        )
