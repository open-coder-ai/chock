"""`install-ci`: idempotent, never clobbers an unrelated file, and gates the coverage claim."""

from __future__ import annotations

from pathlib import Path

from chock.compile.surfaces import Surface, coverage_level
from chock.scaffold.install_ci import MARKER, ci_workflow_installed, main


def test_install_writes_the_workflow(tmp_path: Path) -> None:
    assert main([str(tmp_path)]) == 0
    dest = tmp_path / ".github" / "workflows" / "chock.yml"
    assert dest.exists()
    assert MARKER in dest.read_text(encoding="utf-8")


def test_install_is_idempotent(tmp_path: Path) -> None:
    assert main([str(tmp_path)]) == 0
    dest = tmp_path / ".github" / "workflows" / "chock.yml"
    first = dest.read_bytes()
    assert main([str(tmp_path)]) == 0
    assert dest.read_bytes() == first


def test_install_refuses_to_clobber_an_unrelated_workflow(tmp_path: Path) -> None:
    dest = tmp_path / ".github" / "workflows" / "chock.yml"
    dest.parent.mkdir(parents=True)
    dest.write_text("name: someone-elses-workflow\n", encoding="utf-8")

    assert main([str(tmp_path)]) != 0
    assert dest.read_text(encoding="utf-8") == "name: someone-elses-workflow\n"


def test_ci_workflow_installed_is_false_until_the_marker_is_present(tmp_path: Path) -> None:
    assert ci_workflow_installed(tmp_path) is False
    main([str(tmp_path)])
    assert ci_workflow_installed(tmp_path) is True


def test_coverage_does_not_credit_ci_gate_until_install_ci_has_run() -> None:
    """The exact defect this PR fixes, pinned at the coverage layer: emitting a compiled"""
    emitted = {Surface.CI_GATE, Surface.AMBIENT_RULE}
    assert coverage_level(emitted, "cursor", ci_gate_installed=False) == "advisory"
    assert coverage_level(emitted, "cursor", ci_gate_installed=True) == "enforced-at-commit"


def test_coverage_still_credits_git_hook_alongside_uninstalled_ci_gate() -> None:
    """git-hook's claim does not regress: it is installed automatically by `recompile` and is"""
    emitted = {Surface.GIT_HOOK, Surface.CI_GATE}
    assert coverage_level(emitted, "cursor", ci_gate_installed=False) == "enforced-at-commit"
