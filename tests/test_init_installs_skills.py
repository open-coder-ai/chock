"""`init` must leave a repo an agent can actually work in."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

FRAMEWORK_ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git required")


def _ac(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "chock.cli", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env={**os.environ, "PYTHONPATH": str(FRAMEWORK_ROOT / "src")},
    )


@pytest.fixture
def scaffolded(tmp_path: Path) -> tuple[Path, subprocess.CompletedProcess]:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "--quiet"], cwd=repo, check=True, capture_output=True)
    result = _ac(["init", ".", "--skip-hooks"], repo)
    assert result.returncode == 0, result.stdout + result.stderr
    return repo, result


def _installed(repo: Path) -> list[str]:
    skills = repo / ".agents" / "skills"
    return sorted(p.name for p in skills.iterdir() if p.is_dir()) if skills.is_dir() else []


def test_init_installs_the_authoring_skills(scaffolded: tuple[Path, subprocess.CompletedProcess]) -> None:
    from chock.scaffold.skills import AUTHORING_SKILLS

    repo, _ = scaffolded
    missing = sorted(set(AUTHORING_SKILLS) - set(_installed(repo)))
    assert not missing, f"init left these skills uninstalled: {missing}"


def test_init_says_which_skills_it_installed(scaffolded: tuple[Path, subprocess.CompletedProcess]) -> None:
    """An empty directory with no explanation is what sent an adopter looking for a bug."""
    _, result = scaffolded
    output = result.stdout + result.stderr
    assert "Skills:" in output, output
    assert "policy-init" in output, output


def test_init_still_installs_no_policies(scaffolded: tuple[Path, subprocess.CompletedProcess]) -> None:
    """The distinction this rests on: skills are mechanism, policies are content."""
    repo, _ = scaffolded
    policies = repo / ".agents" / "policies"
    folders = sorted(p.name for p in policies.iterdir() if p.is_dir())
    assert not folders, f"init installed policies it does not own: {folders}"


def test_a_second_init_does_not_discard_an_edited_skill(scaffolded: tuple[Path, subprocess.CompletedProcess]) -> None:
    """`install_skills` replaces a skill wholesale, so `init` must not call it unguarded."""
    repo, _ = scaffolded
    skill = repo / ".agents" / "skills" / "policy-init" / "SKILL.md"
    skill.write_text(skill.read_text(encoding="utf-8") + "\n<!-- our house convention -->\n", encoding="utf-8")

    assert _ac(["init", ".", "--skip-hooks"], repo).returncode == 0
    assert "house convention" in skill.read_text(encoding="utf-8"), "a second init destroyed an edited skill"


def test_install_skills_still_refreshes_on_request(scaffolded: tuple[Path, subprocess.CompletedProcess]) -> None:
    """Preservation is `init`'s rule, not a ban. Asking explicitly must still overwrite."""
    repo, _ = scaffolded
    skill = repo / ".agents" / "skills" / "policy-init" / "SKILL.md"
    skill.write_text("clobbered\n", encoding="utf-8")

    assert _ac(["install-skills", "."], repo).returncode == 0
    assert skill.read_text(encoding="utf-8") != "clobbered\n", "install-skills did not refresh the skill"
