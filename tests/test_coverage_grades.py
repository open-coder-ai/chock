"""The grading ladder, and the distinction it was extended to be able to make."""

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

ALL_SURFACES = tuple(Surface)

FAIL_OPEN_AGENTS = [
    a for a in sorted(SURFACE_AGENTS) if in_agent_level(a, degrades_to=DEGRADES_TO_ALLOW) == "best-effort"
]


def test_the_ladder_is_ordered_weakest_first() -> None:
    """`level_rank` has to be a real order, or "stronger than" is not a question a caller can ask."""
    ranks = [level_rank(level) for level in IN_AGENT_LEVELS]
    assert ranks == sorted(ranks), f"{IN_AGENT_LEVELS} is not ordered by its own rank"
    assert len(set(ranks)) == len(ranks), "two levels share a rank; they would compare equal"
    assert IN_AGENT_LEVELS[0] == "none"
    assert IN_AGENT_LEVELS[-1] == "enforced"


def test_the_new_level_sits_between_best_effort_and_enforceable() -> None:
    """Where `fail-to-ask` was placed, stated as a checkable fact rather than left to the prose."""
    assert level_rank("best-effort") < level_rank("fail-to-ask") < level_rank("enforceable")


def test_unranked_levels_refuse_a_rank_rather_than_inventing_one() -> None:
    """Ranking a git hook against an in-agent hook would be the translation the module refuses."""
    for level in UNRANKED_LEVELS:
        with pytest.raises(ValueError) as excinfo:
            level_rank(level)
        assert level in str(excinfo.value)


def test_degrading_to_a_prompt_grades_strictly_stronger_than_degrading_to_allowing() -> None:
    """The case that motivated the whole change, and the one it must not get wrong."""
    assert FAIL_OPEN_AGENTS, "no fail-open agent left to test the distinction on"
    for agent in FAIL_OPEN_AGENTS:
        allowing = in_agent_level(agent, degrades_to=DEGRADES_TO_ALLOW)
        asking = in_agent_level(agent, degrades_to=DEGRADES_TO_ASK)
        assert level_rank(asking) > level_rank(allowing), (
            f"{agent}: a control that asks ({asking}) does not outrank one that allows ({allowing})"
        )
        assert asking == "fail-to-ask"


def test_a_deny_on_failure_is_graded_no_lower_than_an_ask() -> None:
    """Denying when it cannot decide is stronger than asking; it must never grade weaker."""
    for agent in FAIL_OPEN_AGENTS:
        denying = in_agent_level(agent, degrades_to=DEGRADES_TO_DENY)
        asking = in_agent_level(agent, degrades_to=DEGRADES_TO_ASK)
        assert level_rank(denying) >= level_rank(asking)


def test_the_hosts_fail_mode_still_dominates() -> None:
    """Asking cannot rescue a hook that never ran, so it never moves a non-fail-open row."""
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


def _guard(tmp_path: Path, body: str) -> list[str]:
    """A guard script on disk, and the argv the vendored runtime would invoke it with."""
    path = tmp_path / "guard.sh"
    path.write_text(f"#!/usr/bin/env bash\n{body}\n", encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return ["--guard", str(path)]


def _degradation(evaluate_result) -> str:
    """The degradation word for one `evaluate` return value."""
    from chock.gate import guard_runner

    if evaluate_result is None:
        return DEGRADES_TO_ALLOW
    outcome, _reason = evaluate_result
    return DEGRADES_TO_ASK if outcome == guard_runner.VERDICT_ASK else DEGRADES_TO_DENY


def test_chocks_degradation_constant_is_derived_from_the_running_guard(tmp_path: Path, monkeypatch) -> None:
    """`CONTROL_DEGRADES_TO` is checked by running the mechanism, not by reading the constant."""
    from chock.gate import guard_runner

    assert guard_runner.evaluate(_guard(tmp_path, "exit 1"), "rm -rf /", "Bash") is not None

    crashing = _guard(tmp_path, "exit 3")
    observed = {
        "crash": _degradation(guard_runner.evaluate(crashing, "rm -rf /", "Bash")),
        "killed": _degradation(guard_runner.evaluate(_guard(tmp_path, "kill -9 $$"), "rm -rf /", "Bash")),
        "unparseable": _degradation(guard_runner.evaluate(crashing, 'echo "unbalanced', "Bash")),
        "empty command": _degradation(guard_runner.evaluate(crashing, "   ", "Bash")),
    }
    with monkeypatch.context() as no_bash:
        no_bash.setattr(guard_runner, "find_bash", lambda _: None)
        observed["no bash"] = _degradation(guard_runner.evaluate(crashing, "rm -rf /", "Bash"))
    with monkeypatch.context() as impatient:
        impatient.setattr(guard_runner, "_GUARD_TIMEOUT_SECONDS", 1)
        observed["timeout"] = _degradation(guard_runner.evaluate(_guard(tmp_path, "sleep 30"), "rm -rf /", "Bash"))

    weakest = min(observed.values(), key=DEGRADATION_MODES.index)
    assert weakest == CONTROL_DEGRADES_TO, (
        f"the guard runner's weakest degradation is {weakest!r} but "
        f"CONTROL_DEGRADES_TO says {CONTROL_DEGRADES_TO!r} (per path: {observed})"
    )
    assert DEGRADES_TO_ASK in observed.values(), (
        "no path asks any more -- either the ask was removed, in which case this constant and "
        f"the claims in docs/enforcement-surfaces.md must move with it (per path: {observed})"
    )

    assert guard_runner.evaluate(["--guard", str(tmp_path / "absent.sh")], "rm -rf /", "Bash") is None


def test_chock_does_not_award_itself_the_new_level() -> None:
    """The point of the ladder is that it can say we are behind, so this pins that it does."""
    assert CONTROL_DEGRADES_TO == DEGRADES_TO_ALLOW
    assert coverage_level({Surface.PRE_TOOL_USE}, "claude", pre_tool_use_installed=True) == "best-effort"
    assert coverage_level({Surface.AGENT_HOOKS}, "copilot", agent_hooks_installed=True) == "best-effort"
    assert coverage_level({Surface.AGENT_HOOKS}, "vscode", agent_hooks_installed=True) == "best-effort"
    assert coverage_level({Surface.PRE_TOOL_USE}, "cursor", pre_tool_use_installed=True) == "enforceable"

    reported = {
        coverage_level({s}, a, pre_tool_use_installed=True, agent_hooks_installed=True, ci_gate_installed=True)
        for a in SURFACE_AGENTS
        for s in ALL_SURFACES
    }
    assert "fail-to-ask" not in reported, (
        "a surface now reports `fail-to-ask`; chock's guard still degrades to allow, so this is an overclaim"
    )


def test_every_level_the_code_can_report_is_in_the_published_vocabulary() -> None:
    """`COVERAGE_LEVELS` is what the docs are checked against, so it has to be complete."""
    reported = {
        coverage_level({s}, a, pre_tool_use_installed=p, agent_hooks_installed=h, ci_gate_installed=c)
        for a in list(SURFACE_AGENTS) + ["no-such-agent"]
        for s in ALL_SURFACES
        for p in (True, False)
        for h in (True, False)
        for c in (True, False)
    }
    assert reported <= set(COVERAGE_LEVELS), f"unpublished level(s): {sorted(reported - set(COVERAGE_LEVELS))}"
