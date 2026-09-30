"""A coverage cell names every point a gate holds at: the commit, and the tool call where a hook is installed."""

from __future__ import annotations

from chock.compile.levels import Grade, render_grade
from chock.compile.surfaces import Surface, coverage_cell

BOTH = {Surface.GIT_HOOK, Surface.PRE_TOOL_USE}


def test_an_installed_tool_use_hook_beside_a_git_hook_names_both_points() -> None:
    cell = coverage_cell(BOTH, "claude", pre_tool_use_installed=True)
    assert cell.at_commit and cell.level == "best-effort"
    assert render_grade(cell) == f"enforced-at-commit + best-effort at tool use ({cell.basis})"


def test_a_commit_only_gate_keeps_its_single_word() -> None:
    cell = coverage_cell({Surface.GIT_HOOK}, "claude")
    assert cell == Grade("enforced-at-commit", None, witnessed=False)
    assert render_grade(cell) == "enforced-at-commit"


def test_a_tool_use_hook_with_no_commit_gate_claims_no_commit_point() -> None:
    cell = coverage_cell({Surface.PRE_TOOL_USE}, "claude", pre_tool_use_installed=True)
    assert not cell.at_commit
    assert render_grade(cell) == f"best-effort ({cell.basis})"


def test_a_hook_that_nothing_installed_claims_no_tool_use_point() -> None:
    cell = coverage_cell(BOTH, "claude")
    assert cell.level == "enforced-at-commit" and render_grade(cell) == "enforced-at-commit"


def test_ci_counts_as_a_commit_point_only_once_installed() -> None:
    surfaces = {Surface.CI_GATE, Surface.PRE_TOOL_USE}
    assert not coverage_cell(surfaces, "claude", pre_tool_use_installed=True).at_commit
    assert coverage_cell(surfaces, "claude", pre_tool_use_installed=True, ci_gate_installed=True).at_commit


def test_a_coverage_file_written_before_the_field_still_reads() -> None:
    old = {"level": "best-effort", "basis": "live-run", "witnessed": False}
    assert render_grade(Grade(**old)) == "best-effort (live-run)"
