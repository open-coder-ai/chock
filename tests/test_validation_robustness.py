"""Audit-survivor fixes (issue #49): robustness gaps I3, I6."""

from pathlib import Path

import chock.validation as validator
from chock.validation.report import Report


def _run_eval_check(artifact_dir: Path, report: Report) -> None:
    validator.check_eval_first(artifact_dir, {}, "hook", report)


def test_top_level_list_suite_is_a_finding_not_a_traceback(tmp_path):
    """I3: a suite.yaml whose top level is a list crashed the whole validate run."""
    suite_dir = tmp_path / "evals"
    suite_dir.mkdir()
    (suite_dir / "suite.yaml").write_text("- just\n- a\n- list\n", encoding="utf-8")
    report = Report()
    _run_eval_check(tmp_path, report)
    assert any("mapping" in f.message for f in report.errors)


def test_non_mapping_eval_suite_key_is_a_finding(tmp_path):
    suite_dir = tmp_path / "evals"
    suite_dir.mkdir()
    (suite_dir / "suite.yaml").write_text("eval_suite: just-a-string\n", encoding="utf-8")
    report = Report()
    _run_eval_check(tmp_path, report)
    assert any("mapping" in f.message for f in report.errors)


def test_non_list_cases_is_a_finding(tmp_path):
    suite_dir = tmp_path / "evals"
    suite_dir.mkdir()
    (suite_dir / "suite.yaml").write_text("eval_suite:\n  cases: not-a-list\n", encoding="utf-8")
    report = Report()
    _run_eval_check(tmp_path, report)
    assert any("list" in f.message for f in report.errors)


def test_bracketed_changelog_heading_is_compared_not_skipped(tmp_path):
    """I6: Keep-a-Changelog `## [x.y.z]` headings silently passed the version check."""
    (tmp_path / "pyproject.toml").write_text('[project]\nversion = "9.9.9"\n', encoding="utf-8")
    (tmp_path / "CHANGELOG.md").write_text("# Log\n\n## [1.2.3] - 2026-08-22\n- x\n", encoding="utf-8")
    report = Report()
    validator.check_release_consistency(tmp_path, report)
    assert any("1.2.3" in f.message and "9.9.9" in f.message for f in report.errors), (
        "bracketed heading must be captured and mismatch reported (I6)"
    )


def test_matching_bracketed_heading_passes(tmp_path):
    (tmp_path / "pyproject.toml").write_text('[project]\nversion = "1.2.3"\n', encoding="utf-8")
    (tmp_path / "CHANGELOG.md").write_text("# Log\n\n## [1.2.3] - 2026-08-22\n- x\n", encoding="utf-8")
    report = Report()
    validator.check_release_consistency(tmp_path, report)
    assert not [f for f in report.errors if "CHANGELOG" in f.message or "changelog" in f.path.lower()]
