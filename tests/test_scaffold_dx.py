"""DX regression tests: new/install-skills leave the repo valid, skills stay canonical."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

FRAMEWORK_ROOT = Path(__file__).resolve().parents[1]
PYTHONPATH = str(FRAMEWORK_ROOT / "src") + os.pathsep + os.environ.get("PYTHONPATH", "")


def _run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["PYTHONPATH"] = PYTHONPATH
    return subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, env=env)


def _init(repo: Path) -> Path:
    repo.mkdir()
    _run([sys.executable, "-m", "chock.cli", "init", str(repo), "--skip-hooks"], repo)
    return repo


def test_new_policy_validates_clean(tmp_path: Path) -> None:
    """`new policy` refreshes the registry so `validate` passes immediately (no stale-registry error)."""
    repo = _init(tmp_path / "r")
    _run([sys.executable, "-m", "chock.cli", "new", "policy", "block-demo"], repo)
    result = _run([sys.executable, "-m", "chock.cli", "validate", str(repo)], repo)
    assert result.returncode == 0, result.stdout + result.stderr


def test_install_skills_are_canonical_and_validate_clean(tmp_path: Path) -> None:
    """Skills stay canonical in .agents/skills; refresh wires the .claude/skills bridge."""
    repo = _init(tmp_path / "r")
    _run([sys.executable, "-m", "chock.cli", "install-skills", str(repo)], repo)

    assert (repo / ".agents" / "skills" / "policy-init").exists()
    assert (repo / ".claude" / "skills" / "policy-init").exists()
    assert not (repo / ".github" / "skills").exists()
    assert not (repo / ".cursor" / "skills").exists()

    result = _run([sys.executable, "-m", "chock.cli", "validate", str(repo)], repo)
    assert result.returncode == 0, result.stdout + result.stderr
