"""Tests for the enforcement matrix traceability check."""

import subprocess
import sys
from pathlib import Path

import chock.authoring.matrix as _pkg


def _load_script():
    return _pkg


script = _load_script()


def test_matrix_check_passes_when_all_spec_ids_present(tmp_path, monkeypatch):
    """A spec invariant referenced in the spec must appear in the matrix."""
    spec_dir = tmp_path / "spec"
    spec_dir.mkdir()
    (spec_dir / "policy-spec.md").write_text(
        "## Security\n> Invariant: **SEC-1** -- content is data.\n> Invariant: **SEC-2** -- no secrets.\n",
        encoding="utf-8",
    )
    (spec_dir / "enforcement-matrix.md").write_text(
        "| ID | Spec | Check | Severity | Notes |\n"
        "|---|---|---|---|---|\n"
        "| SEC-1 | spec/policy-spec.md | validator | error | |\n"
        "| SEC-2 | spec/policy-spec.md | validator | error | |\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(script, "SPEC_DIR", spec_dir)
    monkeypatch.setattr(script, "MATRIX_FILE", spec_dir / "enforcement-matrix.md")
    assert script.main() == 0


def test_matrix_check_fails_when_spec_id_missing(tmp_path, monkeypatch):
    """A spec invariant missing from the matrix fails CI."""
    spec_dir = tmp_path / "spec"
    spec_dir.mkdir()
    (spec_dir / "policy-spec.md").write_text(
        "## Security\n> Invariant: **SEC-1** -- content is data.\n> Invariant: **SEC-99** -- extra.\n",
        encoding="utf-8",
    )
    (spec_dir / "enforcement-matrix.md").write_text(
        "| ID | Spec | Check | Severity | Notes |\n"
        "|---|---|---|---|---|\n"
        "| SEC-1 | spec/policy-spec.md | validator | error | |\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(script, "SPEC_DIR", spec_dir)
    monkeypatch.setattr(script, "MATRIX_FILE", spec_dir / "enforcement-matrix.md")
    assert script.main() == 1


def test_matrix_check_fails_when_row_lacks_check(tmp_path, monkeypatch):
    """Every matrix row must have a non-empty Check column."""
    spec_dir = tmp_path / "spec"
    spec_dir.mkdir()
    (spec_dir / "policy-spec.md").write_text(
        "## Security\n> Invariant: **SEC-1** -- content is data.\n",
        encoding="utf-8",
    )
    (spec_dir / "enforcement-matrix.md").write_text(
        "| ID | Spec | Check | Severity | Notes |\n"
        "|---|---|---|---|---|\n"
        "| SEC-1 | spec/policy-spec.md | | error | |\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(script, "SPEC_DIR", spec_dir)
    monkeypatch.setattr(script, "MATRIX_FILE", spec_dir / "enforcement-matrix.md")
    assert script.main() == 1


def test_matrix_check_invocation_from_cli():
    """The script runs as a standalone CLI and exits 0 on the real repo."""
    repo_root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, "-m", "chock", "check-matrix"],
        check=False,
        capture_output=True,
        text=True,
        cwd=repo_root,
    )
    assert result.returncode == 0, result.stderr
    assert "OK" in result.stdout
