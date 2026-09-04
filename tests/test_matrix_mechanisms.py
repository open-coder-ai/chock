"""Tests for the T2 matrix-vs-code mechanism check (checks_matrix_mechanisms.py + matrix_callgraph.py)."""

from __future__ import annotations

from pathlib import Path

from chock.validation import checks_matrix_mechanisms as mech
from chock.validation import matrix_callgraph as cg
from chock.validation.report import Report

REPO_ROOT = Path(__file__).resolve().parents[1]

_FIXTURE_ENGINE = '''\
"""Fixture engine.py: the `chock validate` dispatch path."""
from chock.validation.checks_fixture import check_warn_only
from chock.validation.report import Report


def main() -> int:
    report = Report()
    check_warn_only(report)
    return 0
'''

_FIXTURE_LIFECYCLE = '''\
"""Fixture lifecycle.py: the `chock check` dispatch path (empty for this fixture)."""
'''

_FIXTURE_CHECK_MODULE = '''\
"""Fixture check module: a real function that only ever emits a warning."""
from chock.validation.report import Finding, Report


def check_warn_only(report: Report) -> None:
    report.add(Finding("fixture", "warn_only", "warning", "just a warning"))
'''


def _write_fixture_repo(tmp_path: Path, matrix_text: str) -> Path:
    (tmp_path / "spec").mkdir()
    (tmp_path / "spec" / "enforcement-matrix.md").write_text(matrix_text, encoding="utf-8")
    src = tmp_path / "src" / "chock" / "validation"
    src.mkdir(parents=True)
    (tmp_path / "src" / "chock" / "lifecycle.py").write_text(_FIXTURE_LIFECYCLE, encoding="utf-8")
    (src / "engine.py").write_text(_FIXTURE_ENGINE, encoding="utf-8")
    (src / "checks_fixture.py").write_text(_FIXTURE_CHECK_MODULE, encoding="utf-8")
    return tmp_path


_MATRIX_HEADER = "| ID | Spec | Check | Severity | Notes |\n|---|---|---|---|---|\n"


def test_fails_on_nonexistent_function(tmp_path):
    """A row naming a function that isn't defined anywhere in src/ must fail."""
    matrix = _MATRIX_HEADER + "| BAD-1 | spec/x.md | `does_not_exist()` | error | |\n"
    repo = _write_fixture_repo(tmp_path, matrix)
    report = Report()
    mech.check_matrix_mechanisms(repo, report)
    assert not report.is_clean()
    assert any("BAD-1" in f.message and "not defined" in f.message for f in report.errors)


def test_fails_when_claimed_severity_unachievable(tmp_path):
    """A row claiming `error` for a function that only ever emits `warning` must fail."""
    matrix = _MATRIX_HEADER + "| BAD-2 | spec/x.md | `check_warn_only()` | error | |\n"
    repo = _write_fixture_repo(tmp_path, matrix)
    report = Report()
    mech.check_matrix_mechanisms(repo, report)
    assert not report.is_clean()
    assert any("BAD-2" in f.message and "cannot emit severity 'error'" in f.message for f in report.errors)


def test_passes_when_severity_matches_reality(tmp_path):
    """A row claiming the severity the function actually emits must pass."""
    matrix = _MATRIX_HEADER + "| GOOD-1 | spec/x.md | `check_warn_only()` | warning | |\n"
    repo = _write_fixture_repo(tmp_path, matrix)
    report = Report()
    mech.check_matrix_mechanisms(repo, report)
    assert report.is_clean()


def test_fails_when_no_mechanism_named_and_not_marked_unautomated(tmp_path):
    """A row with prose but no `function()` reference and a real severity must fail, not be silently skipped."""
    matrix = _MATRIX_HEADER + "| BAD-3 | spec/x.md | some manual process | error | |\n"
    repo = _write_fixture_repo(tmp_path, matrix)
    report = Report()
    mech.check_matrix_mechanisms(repo, report)
    assert not report.is_clean()
    assert any("BAD-3" in f.message and "names no" in f.message for f in report.errors)


def test_unautomated_row_is_skipped_knowingly_not_silently(tmp_path):
    """Severity `unautomated` (or `eval`) is skipped, but surfaces as an info finding."""
    matrix = _MATRIX_HEADER + "| UNA-1 | spec/x.md | manual sync, no code path | unautomated | |\n"
    repo = _write_fixture_repo(tmp_path, matrix)
    report = Report()
    mech.check_matrix_mechanisms(repo, report)
    assert report.is_clean()
    assert any("UNA-1" in f.message and "skipped knowingly" in f.message for f in report.infos)


def test_function_not_invoked_on_either_path_fails(tmp_path):
    """A function that exists but is never called from engine.py or lifecycle.py must fail."""
    matrix = _MATRIX_HEADER + "| BAD-4 | spec/x.md | `check_dead()` | error | |\n"
    repo = _write_fixture_repo(tmp_path, matrix)
    dead = (
        "from chock.validation.report import Finding, Report\n\n\n"
        "def check_dead(report: Report) -> None:\n"
        '    report.add(Finding("fixture", "dead", "error", "never called"))\n'
    )
    (repo / "src" / "chock" / "validation" / "checks_dead.py").write_text(dead, encoding="utf-8")
    report = Report()
    mech.check_matrix_mechanisms(repo, report)
    assert not report.is_clean()
    assert any("BAD-4" in f.message and "not invoked" in f.message for f in report.errors)


def test_lifecycle_only_check_is_not_reported_as_missing():
    """Regression for the audit's own false positive: a lifecycle-only check must not read as unwired.

    `check_ambient_conflicts` is only ever called from `checks_conflicts.py`, which
    `lifecycle.py` imports dynamically inside `chock check --only conflicts`. `engine.py`
    never touches it. Checking engine.py alone (the audit's first, wrong pass) would report
    it missing; both dispatch paths together must not.
    """
    modules = cg.load_modules(REPO_ROOT / "src")
    lifecycle_only = cg.reachable_modules(modules, ("chock.lifecycle",))
    engine_only = cg.reachable_modules(modules, ("chock.validation.engine",))

    assert "chock.validation.checks_conflicts" in lifecycle_only
    assert "chock.validation.checks_conflicts" not in engine_only

    graph = cg.build_call_graph(modules)
    verdict = cg.verify_mechanism(graph, lifecycle_only | engine_only, "check_ambient_conflicts")
    assert verdict.exists
    assert verdict.invoked


def test_matrix_mechanisms_check_passes_on_real_repo():
    """The real spec/enforcement-matrix.md, once T1/T3/T4 land, must pass the mechanism check."""
    report = Report()
    mech.check_matrix_mechanisms(REPO_ROOT, report)
    assert report.is_clean(), [f.message for f in report.errors]


def test_mechanisms_check_invocation_from_cli():
    """The script runs as `chock check --only mechanisms` and exits 0 on the real repo."""
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, "-m", "chock", "check", "--only", "mechanisms"],
        check=False,
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    assert result.returncode == 0, result.stdout + result.stderr
