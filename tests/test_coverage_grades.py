"""The grading ladder, and the distinction it was extended to be able to make.

agentseam's five words -- `enforced` / `enforceable` / `best-effort` / `detect` / `none` --
read one axis: what the HOST does when our hook never runs. Two materially different controls
therefore collapsed onto `best-effort`: one that degrades to silently allowing, and one that
degrades to putting the action to a human. The second is strictly stronger, and a grading
layer that cannot say so cannot rank a competitor above us -- which is a defect in the
grading layer, not a detail, because being able to report that we are behind is the whole
reason anyone should believe the grades that flatter us.

`fail-to-ask` is that missing word. These tests pin three things: that the ladder is ordered
and the ordering is usable, that the new level is DERIVED from the mechanism rather than
asserted per agent, and -- the one that matters most -- that chock does not quietly award
itself the new level. `CONTROL_DEGRADES_TO` is checked against the guard runner actually
running, not taken on trust.
"""

from __future__ import annotations

import stat
from pathlib import Path

import pytest

from chock.compile.levels import (
    CONTROL_DEGRADES_TO,
    COVERAGE_LEVELS,
    DEGRADATION_MODES,
    DEGRADES_TO_ALLOW,
    DEGRADES_TO_ASK,
    DEGRADES_TO_DENY,
    IN_AGENT_LEVELS,
    UNRANKED_LEVELS,
    in_agent_level,
    level_rank,
)
from chock.compile.surfaces import SURFACE_AGENTS, Surface, coverage_level

#: Agents whose host fails OPEN at the outer boundary -- the rows where the old vocabulary
#: could not tell the two controls apart, and so the rows the new level applies to. Derived
#: rather than listed: an agent qualifies precisely when its allow-degrading grade is the
#: `best-effort` tier, which is the condition `in_agent_level` itself branches on.
FAIL_OPEN_AGENTS = [
    a for a in sorted(SURFACE_AGENTS) if in_agent_level(a, degrades_to=DEGRADES_TO_ALLOW) == "best-effort"
]


def test_the_ladder_is_ordered_weakest_first() -> None:
    """`level_rank` has to be a real order, or "stronger than" is not a question a caller can ask."""
    ranks = [level_rank(level) for level in IN_AGENT_LEVELS]
    assert ranks == sorted(ranks), f"{IN_AGENT_LEVELS} is not ordered by its own rank"
    assert len(set(ranks)) == len(ranks), "two levels share a rank; they would compare equal"
    # The two ends are the claims the ladder is anchored on, so they are pinned by name.
    assert IN_AGENT_LEVELS[0] == "none"
    assert IN_AGENT_LEVELS[-1] == "enforced"


def test_the_new_level_sits_between_best_effort_and_enforceable() -> None:
    """Where `fail-to-ask` was placed, stated as a checkable fact rather than left to the prose.

    Above `best-effort` because the action does not proceed unattended; below `enforceable`
    because asking always needs a person present and a configured fail-closed hook does not.
    """
    assert level_rank("best-effort") < level_rank("fail-to-ask") < level_rank("enforceable")


def test_unranked_levels_refuse_a_rank_rather_than_inventing_one() -> None:
    """Ranking a git hook against an in-agent hook would be the translation the module refuses.

    Returning some plausible number is the failure mode worth guarding: it reads as an
    answer, and every caller comparing strengths would then be comparing mechanisms that
    have no common scale.
    """
    for level in UNRANKED_LEVELS:
        with pytest.raises(ValueError) as excinfo:
            level_rank(level)
        assert level in str(excinfo.value)


def test_degrading_to_a_prompt_grades_strictly_stronger_than_degrading_to_allowing() -> None:
    """The case that motivated the whole change, and the one it must not get wrong.

    A control that blocks and, when it cannot decide, asks a human, versus one that blocks
    and, when it cannot decide, lets the command through. The old vocabulary gave both the
    same word. This asserts a strict inequality in rank, not merely that the strings differ.
    """
    assert FAIL_OPEN_AGENTS, "no fail-open agent left to test the distinction on"
    for agent in FAIL_OPEN_AGENTS:
        allowing = in_agent_level(agent, degrades_to=DEGRADES_TO_ALLOW)
        asking = in_agent_level(agent, degrades_to=DEGRADES_TO_ASK)
        assert level_rank(asking) > level_rank(allowing), (
            f"{agent}: a control that asks ({asking}) does not outrank one that allows ({allowing})"
        )
        assert asking == "fail-to-ask"


def test_a_deny_on_failure_is_graded_no_lower_than_an_ask() -> None:
    """Denying when it cannot decide is stronger than asking; it must never grade weaker.

    Graded the same rather than higher, deliberately: the ladder ranks on whether the action
    proceeds unattended, and a control whose hook never starts denies nobody either.
    """
    for agent in FAIL_OPEN_AGENTS:
        denying = in_agent_level(agent, degrades_to=DEGRADES_TO_DENY)
        asking = in_agent_level(agent, degrades_to=DEGRADES_TO_ASK)
        assert level_rank(denying) >= level_rank(asking)


def test_the_hosts_fail_mode_still_dominates() -> None:
    """Asking cannot rescue a hook that never ran, so it never moves a non-fail-open row.

    Cursor is the live case: FAIL_CONFIGURABLE, so `enforceable` whatever our guard does. If
    this ever loosened, a control could be promoted on our own say-so past a boundary that is
    the host's to set -- exactly the overclaim the surrounding module exists to refuse.
    """
    not_fail_open = [a for a in sorted(SURFACE_AGENTS) if a not in FAIL_OPEN_AGENTS]
    assert "cursor" in not_fail_open
    for agent in not_fail_open:
        grades = {in_agent_level(agent, degrades_to=mode) for mode in DEGRADATION_MODES}
        assert len(grades) == 1, f"{agent} changed grade on our degradation alone: {grades}"


def test_an_unknown_degradation_mode_is_refused() -> None:
    """A typo must not silently take the `allow` branch and understate, or the `ask` one and overstate."""
    with pytest.raises(ValueError):
        in_agent_level("claude", degrades_to="fail-safe")


def test_an_unmapped_agent_has_no_in_agent_level() -> None:
    assert in_agent_level("no-such-agent") == "none"
    assert in_agent_level("codex") == "none", "codex has no in-agent surface in SURFACE_AGENTS"


# ---------------------------------------------------------------------------------------
# The half that keeps this honest: what chock's own control actually does.
# ---------------------------------------------------------------------------------------


def _guard(tmp_path: Path, body: str) -> list[str]:
    """A guard script on disk, and the argv the vendored runtime would invoke it with."""
    path = tmp_path / "guard.sh"
    path.write_text(f"#!/usr/bin/env bash\n{body}\n", encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return ["--guard", str(path)]


def test_chocks_degradation_constant_is_derived_from_the_running_guard(tmp_path: Path) -> None:
    """`CONTROL_DEGRADES_TO` is checked by running the mechanism, not by reading the constant.

    A constant that merely says "we fail open" would keep saying it after someone wired an
    ask path in, and the grade would then understate. So the value is recomputed here from
    what `gate.guard_runner.evaluate` returns for a guard that ran and could not decide, and
    compared to the constant `coverage_level` reads.

    The blocking case is asserted alongside it on purpose: without it, "degrades to allow"
    would also be true of a control that allows everything, and the test would pass for the
    wrong reason.
    """
    from chock.gate import guard_runner

    # Exit 1 is the violation channel: the control really does block.
    assert guard_runner.evaluate(_guard(tmp_path, "exit 1"), "rm -rf /", "Bash") is not None

    # Exit 3 is "the check did not happen" -- a crash, in the runner's own words. Whatever
    # it returns for that IS chock's degradation, and `evaluate` has only two channels:
    # a deny reason, or None (which the vendored dispatch turns into no opinion, i.e. allow).
    degraded = guard_runner.evaluate(_guard(tmp_path, "exit 3"), "rm -rf /", "Bash")
    observed = DEGRADES_TO_ALLOW if degraded is None else DEGRADES_TO_DENY
    assert observed == CONTROL_DEGRADES_TO, (
        f"the guard runner degrades to {observed!r} but CONTROL_DEGRADES_TO says {CONTROL_DEGRADES_TO!r}"
    )
    # And the same for the other "not checked" routes, so the constant covers the class
    # rather than the one path this test happened to take.
    assert guard_runner.evaluate(_guard(tmp_path, "kill -9 $$"), "rm -rf /", "Bash") is None
    assert guard_runner.evaluate(["--guard", str(tmp_path / "absent.sh")], "rm -rf /", "Bash") is None


def test_chock_does_not_award_itself_the_new_level() -> None:
    """The point of the ladder is that it can say we are behind, so this pins that it does.

    chock's PreToolUse and agent-hooks surfaces stay at the weaker tier while the vocabulary
    now has a word for something we do not do. If someone wires an ask path in, this test
    fails and is meant to -- the grade moves with the mechanism, and the mechanism is what
    would have changed.
    """
    assert CONTROL_DEGRADES_TO == DEGRADES_TO_ALLOW
    assert coverage_level({Surface.PRE_TOOL_USE}, "claude", pre_tool_use_installed=True) == "best-effort"
    assert coverage_level({Surface.AGENT_HOOKS}, "copilot", agent_hooks_installed=True) == "best-effort"
    assert coverage_level({Surface.AGENT_HOOKS}, "vscode", agent_hooks_installed=True) == "best-effort"
    # Cursor is `enforceable` for the host's reason, not ours -- included so a reader does not
    # take the three rows above as the whole story.
    assert coverage_level({Surface.PRE_TOOL_USE}, "cursor", pre_tool_use_installed=True) == "enforceable"

    reported = {
        coverage_level({s}, a, pre_tool_use_installed=True, agent_hooks_installed=True, ci_gate_installed=True)
        for a in SURFACE_AGENTS
        for s in Surface
    }
    assert "fail-to-ask" not in reported, (
        "a surface now reports `fail-to-ask`; chock's guard still degrades to allow, so this is an overclaim"
    )


def test_every_level_the_code_can_report_is_in_the_published_vocabulary() -> None:
    """`COVERAGE_LEVELS` is what the docs are checked against, so it has to be complete.

    Brute-forced over the witness combinations rather than listed, so a new branch in
    `coverage_level` returning a word nobody published fails here instead of in a reader's
    coverage report.
    """
    reported = {
        coverage_level({s}, a, pre_tool_use_installed=p, agent_hooks_installed=h, ci_gate_installed=c)
        for a in list(SURFACE_AGENTS) + ["no-such-agent"]
        for s in Surface
        for p in (True, False)
        for h in (True, False)
        for c in (True, False)
    }
    assert reported <= set(COVERAGE_LEVELS), f"unpublished level(s): {sorted(reported - set(COVERAGE_LEVELS))}"
