"""Acceptance tests for policy enable/disable/tune behavior."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

FRAMEWORK_ROOT = Path(__file__).resolve().parents[1]
PYTHONPATH = str(FRAMEWORK_ROOT / "src") + os.pathsep + os.environ.get("PYTHONPATH", "")


def _run(cmd: list[str], cwd: Path, check: bool = True) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["PYTHONPATH"] = PYTHONPATH
    result = subprocess.run(
        cmd,
        cwd=str(cwd),
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    if check and result.returncode != 0:
        raise AssertionError(f"Command failed: {cmd}\nstdout: {result.stdout}\nstderr: {result.stderr}")
    return result


def _init_repo(tmp_path: Path) -> Path:
    """A scaffolded repo with this repo's policies copied in."""
    repo = tmp_path / "consumer"
    repo.mkdir()
    _run([sys.executable, "-m", "chock.cli", "init", str(repo), "--skip-hooks"], cwd=repo)
    for src in sorted(p for p in (FRAMEWORK_ROOT / ".agents" / "policies").iterdir() if p.is_dir()):
        shutil.copytree(src, repo / ".agents" / "policies" / src.name)
    _run([sys.executable, "-m", "chock.cli", "recompile", "--repo", str(repo), "--skip-hooks"], cwd=repo)
    _run([sys.executable, "-m", "chock.cli", "refresh", "--repo", str(repo)], cwd=repo)
    _run([sys.executable, "-m", "chock.cli", "registry", "scan"], cwd=repo)
    return repo


def _git_init(repo: Path) -> None:
    _run(["git", "init", "--quiet"], cwd=repo)
    _run(["git", "config", "user.email", "test@example.com"], cwd=repo)
    _run(["git", "config", "user.name", "Test User"], cwd=repo)


def test_disable_removes_compiled_artifacts_and_hook_wrappers(tmp_path: Path) -> None:
    """disabled: [block-no-verify] → no compiled dir, no hook, coverage disabled, verify green."""
    repo = _init_repo(tmp_path)
    _run([sys.executable, "-m", "chock.cli", "disable", "block-no-verify"], cwd=repo)

    assert not (repo / ".chock" / "compiled" / "block-no-verify").exists()
    coverage = json.loads((repo / ".chock" / "coverage.json").read_text())
    assert {a: c["level"] for a, c in coverage["block-no-verify"].items()} == {
        "claude": "disabled",
        "copilot": "disabled",
        "gemini": "disabled",
    }

    result = _run([sys.executable, "-m", "chock.cli", "validate", str(repo)], cwd=repo, check=False)
    assert result.returncode == 0, result.stderr


def test_override_advise_emits_only_ambient_and_allows_commit(tmp_path: Path) -> None:
    """overrides scan-secrets → advise: ambient artifact present, no git-hook, staged secret commit succeeds."""
    if shutil.which("git") is None:
        pytest.skip("git not available")
    if shutil.which("sh") is None:
        pytest.skip("sh not available")

    repo = _init_repo(tmp_path)
    _git_init(repo)
    _run([sys.executable, "-m", "chock.cli", "install-hooks", str(repo)], cwd=repo)

    config = repo / ".chock" / "config.yaml"
    config.write_text(
        config.read_text(encoding="utf-8").rstrip()
        + "\n\npolicies:\n  disabled: []\n  overrides:\n    scan-secrets:\n      enforcement: advise\n",
        encoding="utf-8",
    )

    _run([sys.executable, "-m", "chock.cli", "recompile", "--repo", str(repo)], cwd=repo)

    scan_compiled = repo / ".chock" / "compiled" / "scan-secrets"
    assert (scan_compiled / "ambient-rule" / "ambient.md").exists()
    assert not (scan_compiled / "git-hook").exists()

    _run(["git", "checkout", "-b", "feature/x"], cwd=repo)
    (repo / "secret.txt").write_text("AKIAIOSFODNN7EXAMPLE\n", encoding="utf-8")
    _run(["git", "add", "secret.txt"], cwd=repo)
    result = _run(["git", "commit", "-m", "test"], cwd=repo, check=False)
    assert result.returncode == 0, result.stderr


def test_enable_restores_policy_and_coverage(tmp_path: Path) -> None:
    """enable a disabled policy recompiles it and restores coverage."""
    repo = _init_repo(tmp_path)
    _run([sys.executable, "-m", "chock.cli", "disable", "block-no-verify"], cwd=repo)
    assert not (repo / ".chock" / "compiled" / "block-no-verify").exists()

    _run([sys.executable, "-m", "chock.cli", "enable", "block-no-verify"], cwd=repo)
    assert (repo / ".chock" / "compiled" / "block-no-verify").exists()
    coverage = json.loads((repo / ".chock" / "coverage.json").read_text())
    assert coverage["block-no-verify"]["claude"]["level"] != "disabled"


def test_init_preserves_user_policies_block(tmp_path: Path) -> None:
    """Re-running init preserves the user's policies block and defaults."""
    repo = _init_repo(tmp_path)
    config = repo / ".chock" / "config.yaml"
    config.write_text(
        "chock:\n"
        '  version: "0.0.1"\n'
        "  supported_agents: [claude, cursor, copilot]\n"
        "  agent_agnostic: false\n"
        "  onboarded_at: '2026-01-01T00:00:00Z'\n"
        "  defaults:\n"
        "    verification_command: 'pytest'\n"
        "policies:\n"
        "  disabled: [block-no-verify]\n"
        "  overrides: {}\n",
        encoding="utf-8",
    )

    _run([sys.executable, "-m", "chock.cli", "init", str(repo), "--skip-hooks"], cwd=repo)

    after = yaml.safe_load(config.read_text(encoding="utf-8"))
    assert after["policies"]["disabled"] == ["block-no-verify"]
    assert after["chock"]["defaults"]["verification_command"] == "pytest"


def test_disable_mandatory_refused_and_validate_errors(tmp_path: Path) -> None:
    """disabled: [scan-secrets] is refused by disable and fails validate."""
    repo = _init_repo(tmp_path)
    result = _run([sys.executable, "-m", "chock.cli", "disable", "scan-secrets"], cwd=repo, check=False)
    assert result.returncode == 2
    assert "mandatory" in result.stderr

    config = repo / ".chock" / "config.yaml"
    config.write_text(
        config.read_text(encoding="utf-8").rstrip() + "\n\npolicies:\n  disabled: [scan-secrets]\n  overrides: {}\n",
        encoding="utf-8",
    )
    result = _run([sys.executable, "-m", "chock.cli", "validate", str(repo)], cwd=repo, check=False)
    assert result.returncode == 1
    assert "mandatory" in result.stdout


def test_unknown_disabled_warns_not_crashes(tmp_path: Path) -> None:
    """disabled: [does-not-exist] is warned and validate does not crash."""
    repo = _init_repo(tmp_path)
    config = repo / ".chock" / "config.yaml"
    config.write_text(
        config.read_text(encoding="utf-8").rstrip() + "\n\npolicies:\n  disabled: [does-not-exist]\n  overrides: {}\n",
        encoding="utf-8",
    )
    result = _run([sys.executable, "-m", "chock.cli", "validate", str(repo)], cwd=repo, check=False)
    assert result.returncode == 0
    assert "does-not-exist" in result.stdout


def test_policies_command_lists_states_and_coverage(tmp_path: Path) -> None:
    """chock status prints each policy's state + coverage."""
    repo = _init_repo(tmp_path)
    _run([sys.executable, "-m", "chock.cli", "disable", "block-no-verify"], cwd=repo)
    result = _run([sys.executable, "-m", "chock.cli", "policies"], cwd=repo, check=False)
    assert result.returncode == 0
    assert "block-no-verify" in result.stdout
    assert "disabled" in result.stdout
    assert "scan-secrets" in result.stdout
    assert "mandatory" in result.stdout
