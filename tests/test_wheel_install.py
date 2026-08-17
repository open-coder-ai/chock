"""Clean-venv wheel install acceptance for packaging (P1-A).

The wheel comes from the session-scoped `built_wheel` fixture in conftest, which
builds once from a clean copy. This module used to build it again, in place --
duplicating the work and reusing `build/lib`.
"""

from __future__ import annotations

import subprocess
import sys
import venv
import zipfile
from pathlib import Path

import pytest

pytest.importorskip("build")

FRAMEWORK_ROOT = Path(__file__).resolve().parents[1]


def test_wheel_contains_skills_and_schemas(built_wheel: Path) -> None:
    """The wheel must ship the bundled authoring skills and the validation schemas.

    Policies are deliberately absent -- see tests/test_packaging_boundary.py.
    """
    with zipfile.ZipFile(built_wheel) as whl:
        names = whl.namelist()
    assert any("_skills/" in n for n in names), "skills packs missing"
    assert any("schemas/" in n for n in names), "validation schemas missing"


def test_wheel_installs_and_init_passes(tmp_path: Path, built_wheel: Path) -> None:
    """pip install into a fresh venv, then chock init in a new git repo."""
    venv_dir = tmp_path / "venv"
    venv.create(venv_dir, with_pip=True, clear=True)
    python = venv_dir / ("Scripts" if sys.platform == "win32" else "bin") / "python"
    pip = venv_dir / ("Scripts" if sys.platform == "win32" else "bin") / "pip"

    subprocess.run([str(pip), "install", "--quiet", str(built_wheel)], check=True)

    consumer = tmp_path / "consumer"
    consumer.mkdir()
    subprocess.run(["git", "init", "--quiet"], cwd=str(consumer), check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=str(consumer), check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=str(consumer), check=True)

    result = subprocess.run(
        [str(python), "-m", "chock.cli", "init", str(consumer), "--skip-hooks"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr

    # init scaffolds wiring and installs no policies, so the scaffolding is what proves the
    # wheel is complete -- AGENTS.md and INDEX.md are both written from packaged files.
    assert (consumer / "AGENTS.md").exists(), f"AGENTS.md not scaffolded: {result.stdout}{result.stderr}"
    assert (consumer / ".agents" / "policies" / "INDEX.md").exists(), result.stdout + result.stderr
    assert "enforces nothing yet" in result.stdout, f"init did not say the repo is unguarded: {result.stdout}"


def test_wheel_cli_version_matches_pyproject(built_wheel: Path, tmp_path: Path) -> None:
    """chock --version prints the version from the wheel metadata."""
    import re

    pyproject = (FRAMEWORK_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"([^"]+)"', pyproject, re.MULTILINE)
    assert match
    expected = match.group(1)

    venv_dir = tmp_path / "venv"
    venv.create(venv_dir, with_pip=True, clear=True)
    python = venv_dir / ("Scripts" if sys.platform == "win32" else "bin") / "python"
    pip = venv_dir / ("Scripts" if sys.platform == "win32" else "bin") / "pip"
    subprocess.run([str(pip), "install", "--quiet", str(built_wheel)], check=True)

    result = subprocess.run(
        [str(python), "-m", "chock.cli", "--version"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == expected
