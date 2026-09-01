"""Clean-venv wheel install acceptance for packaging (P1-A)."""

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
    """The wheel must ship the bundled authoring skills and the validation schemas."""
    with zipfile.ZipFile(built_wheel) as whl:
        names = whl.namelist()
    assert any("_skills/" in n for n in names), "skills packs missing"
    assert any("schemas/" in n for n in names), "validation schemas missing"


def test_wheel_contains_the_files_plugin_packages_ship(built_wheel: Path) -> None:
    """`chock plugin build` reads these at emit time, so a wheel without them cannot package."""
    from chock.plugin import listing

    with zipfile.ZipFile(built_wheel) as whl:
        names = set(whl.namelist())
    data_dir = Path(listing.__file__).resolve().parent / "data"
    wanted = sorted(p.name for p in data_dir.iterdir() if p.is_file())
    assert wanted, "the emitter's data directory is empty; this test no longer pins anything"
    missing = [n for n in wanted if f"chock/plugin/data/{n}" not in names]
    assert not missing, f"wheel is missing plugin data {missing}; check [tool.setuptools.package-data]"

    stores_dir = data_dir / "stores"
    stores = sorted(p.name for p in stores_dir.iterdir() if p.is_file())
    assert stores, "the store-data directory is empty; this test no longer pins anything"
    missing_stores = [n for n in stores if f"chock/plugin/data/stores/{n}" not in names]
    assert not missing_stores, f"wheel is missing store data {missing_stores}; check [tool.setuptools.package-data]"


def test_wheel_contains_the_evidence_ledgers(built_wheel: Path) -> None:
    """Grading and package posture read these at run time; a wheel without them cannot compile."""
    from chock import evidence

    with zipfile.ZipFile(built_wheel) as whl:
        names = set(whl.namelist())
    wanted = sorted(p.name for p in evidence.DATA_DIR.iterdir() if p.is_file())
    assert wanted, "the evidence data directory is empty; this test no longer pins anything"
    missing = [n for n in wanted if f"chock/data/{n}" not in names]
    assert not missing, f"wheel is missing evidence data {missing}; check [tool.setuptools.package-data]"


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
