"""A coverage cell names every point a gate holds at: the commit, and the tool call where a hook is installed."""

from __future__ import annotations

from pathlib import Path

import yaml

from chock.compile.compiler import compile_policy
from chock.compile.levels import Grade, render_grade
from chock.compile.surfaces import Surface, coverage_cell

BOTH = {Surface.GIT_HOOK, Surface.PRE_TOOL_USE}


def test_an_installed_tool_use_hook_beside_a_git_hook_names_both_points() -> None:
    cell = coverage_cell(BOTH, "claude", pre_tool_use_installed=True)
    assert cell.at_commit and cell.level == "best-effort"
    assert render_grade(cell) == f"enforced-at-commit + best-effort at tool use ({cell.basis})"


def test_a_commit_only_gate_keeps_its_single_word() -> None:
    cell = coverage_cell({Surface.GIT_HOOK}, "claude")
    assert cell == Grade("enforced-at-commit", None, witnessed=False, at_commit=True)
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
    assert render_grade(Grade.read(old)) == "best-effort (live-run)"
    newer = {**old, "at_commit": True, "a_field_from_a_later_chock": 1}
    assert render_grade(Grade.read(newer)) == "enforced-at-commit + best-effort at tool use (live-run)"


def _git_hook(tmp_path: Path, policy_id: str, hook: dict) -> dict:
    repo = tmp_path / policy_id
    pack = repo / ".agents" / "policies" / policy_id
    (pack / "implementations").mkdir(parents=True)
    manifest = {"id": policy_id, "name": policy_id, "version": "0.0.1", "description": "d", "hook": hook}
    (pack / "manifest.yaml").write_text(yaml.safe_dump(manifest), encoding="utf-8")
    (pack / "implementations" / f"{policy_id}-pre-push.sh").write_text("exit 0\n", encoding="utf-8")
    (pack / "implementations" / f"{policy_id}-pre-commit.sh").write_text("exit 0\n", encoding="utf-8")
    result = compile_policy(pack, targets=["git-hook"], output_root=repo / ".chock/compiled", agents=["aider"])
    return result.coverage[policy_id]["aider"]


def test_a_push_only_hook_claims_no_commit_point(tmp_path: Path) -> None:
    """A pre-push script runs after the commit is made: it never earns `enforced-at-commit`."""
    cell = _git_hook(tmp_path, "push-only", {"script": {"on": ["push"]}})
    assert cell["level"] != "enforced-at-commit" and not cell["at_commit"], cell
    committed = _git_hook(tmp_path, "at-commit", {"script": {"on": ["commit", "push"]}})
    assert committed["level"] == "enforced-at-commit" and committed["at_commit"], committed
