"""Copying a policy in and recompiling must leave a repo you can still commit to."""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import REPO_POLICIES

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git required")


def _run(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(args, cwd=str(cwd), capture_output=True, text=True, encoding="utf-8", errors="replace")


def _ac(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    import os

    return subprocess.run(
        [sys.executable, "-m", "chock.cli", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")},
    )


@pytest.fixture
def adopter(tmp_path: Path) -> Path:
    repo = tmp_path / "adopter"
    repo.mkdir()
    for args in (
        ["git", "init", "--quiet", "."],
        ["git", "config", "user.email", "a@example.invalid"],
        ["git", "config", "user.name", "Adopter"],
        ["git", "config", "commit.gpgsign", "false"],
    ):
        _run(args, repo)
    result = _ac(["init", "."], repo)
    assert result.returncode == 0, result.stdout + result.stderr
    return repo


def _install_policy(repo: Path, policy_id: str) -> None:
    """The documented install: copy the folder, then recompile. Nothing else."""
    shutil.copytree(REPO_POLICIES / policy_id, repo / ".agents" / "policies" / policy_id)
    result = _ac(["recompile", "--repo", "."], repo)
    assert result.returncode == 0, result.stdout + result.stderr


def test_a_copied_policy_enforces_and_leaves_the_repo_usable(adopter: Path) -> None:
    _install_policy(adopter, "protect-main-branch")
    assert _ac(["install-hooks", "."], adopter).returncode == 0

    (adopter / "app.py").write_text("print('x')\n", encoding="utf-8")
    _run(["git", "add", "app.py"], adopter)

    on_main = _run(["git", "commit", "-m", "on main"], adopter)
    assert on_main.returncode != 0, "the copied gate did not enforce"

    _run(["git", "checkout", "-q", "-b", "feature/work"], adopter)
    on_branch = _run(["git", "commit", "-m", "on a branch"], adopter)
    assert on_branch.returncode == 0, (
        "ordinary work was blocked after installing a policy:\n" + on_branch.stdout + on_branch.stderr
    )


def test_recompile_leaves_validation_clean(adopter: Path) -> None:
    """The direct cause, asserted without going through git."""
    _install_policy(adopter, "protect-main-branch")

    result = _ac(["validate", "."], adopter)
    output = result.stdout + result.stderr
    assert result.returncode == 0, f"validate failed after a documented install:\n{output}"
    assert "registry_freshness" not in output, output
    assert "index_freshness" not in output, output


def test_verify_actually_tracks_what_was_installed(adopter: Path) -> None:
    """`verify` must be able to fail."""
    _install_policy(adopter, "protect-main-branch")

    clean = _ac(["verify"], adopter)
    assert clean.returncode == 0, clean.stdout + clean.stderr

    manifest = adopter / ".agents" / "policies" / "protect-main-branch" / "manifest.yaml"
    manifest.write_text(manifest.read_text(encoding="utf-8") + "\n# tampered\n", encoding="utf-8")

    tampered = _ac(["verify"], adopter)
    assert tampered.returncode != 0, (
        "verify passed after an installed policy was edited:\n" + tampered.stdout + tampered.stderr
    )


def test_every_next_step_add_prints_actually_runs(adopter: Path, tmp_path: Path) -> None:
    """The quickstart ends with a paste: `chock add <id>`, then the command `add` names."""
    catalog = tmp_path / "catalog"
    (catalog / "base").mkdir(parents=True)
    shutil.copytree(REPO_POLICIES / "protect-main-branch", catalog / "base" / "protect-main-branch")

    for extra in (["--skip-compile"], ["--force"]):
        result = _ac(["add", "protect-main-branch", "--from", str(catalog), *extra], adopter)
        assert result.returncode == 0, result.stdout + result.stderr

        hints = re.findall(r"Run `chock ([^`]+)`", result.stdout)
        assert hints, f"add ({' '.join(extra)}) printed no next step:\n{result.stdout}"
        for hint in hints:
            follow = _ac(hint.split(), adopter)
            assert follow.returncode == 0, (
                f"the printed next step `chock {hint}` does not run:\n" + follow.stdout + follow.stderr
            )


def test_check_stays_side_effect_free(adopter: Path) -> None:
    """`recompile --check` must measure, never repair."""
    _install_policy(adopter, "protect-main-branch")
    index = adopter / ".agents" / "policies" / "INDEX.md"
    index.write_text("deliberately stale\n", encoding="utf-8")

    _ac(["recompile", "--repo", ".", "--check"], adopter)
    assert index.read_text(encoding="utf-8") == "deliberately stale\n", "--check repaired what it measured"
