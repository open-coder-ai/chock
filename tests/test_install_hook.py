"""End-to-end tests for the Chock git-hook installer."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml
from conftest import baseline_policy

from chock.compile.compiler import compile_policy
from chock.compile.surfaces import Surface
from chock.hooks.install import main as install_main

SKIP_REASON = "sh/bash not available on this platform"


def _sh_available() -> bool:
    return shutil.which("sh") is not None and shutil.which("bash") is not None


def _framework_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "consumer"
    repo.mkdir()
    subprocess.run(["git", "init", "--quiet"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, check=True)
    return repo


def _make_policy(repo: Path, policy_id: str, refs: list[str]) -> Path:
    """Create a minimal declarative hook policy and return its directory."""
    policy_dir = repo / ".agents" / "policies" / policy_id
    policy_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "id": policy_id,
        "name": f"Test {policy_id}",
        "version": "0.0.1",
        "description": "test policy",
        "artifact": "hook",
        "enforcement": "block",
        "hook": {
            "gate": {
                "kind": "forbidden_ref",
                "on": ["commit", "push"],
                "action": "block",
                "message": "blocked by test",
                "params": {"refs": refs},
            }
        },
    }
    (policy_dir / "manifest.yaml").write_text(yaml.safe_dump(manifest), encoding="utf-8")
    return policy_dir


def test_install_py_registers_default_policy_hooks(tmp_path: Path) -> None:
    """install-hooks discovers compiled git-hook shims and registers one wrapper per event."""
    repo = _init_repo(tmp_path)
    policy_dir = baseline_policy("protect-main-branch")
    compile_policy(policy_dir, targets=[Surface.GIT_HOOK.value], output_root=repo / ".chock" / "compiled")

    assert install_main([str(repo)]) == 0

    hooks_dir = repo / ".git" / "hooks"
    assert (hooks_dir / "pre-commit").exists()
    assert (hooks_dir / "pre-push").exists()
    pre_commit_wrappers = list((hooks_dir / "pre-commit.d").glob("50-chock-policy-*"))
    pre_push_wrappers = list((hooks_dir / "pre-push.d").glob("50-chock-policy-*"))
    assert len(pre_commit_wrappers) == 1
    assert len(pre_push_wrappers) == 1


@pytest.mark.skipif(not _sh_available(), reason=SKIP_REASON)
def test_install_py_relocates_existing_hook_and_replays_stdin(tmp_path: Path) -> None:
    """install-hooks preserves an existing pre-push hook and the dispatcher replays stdin."""
    repo = _init_repo(tmp_path)
    hooks_dir = repo / ".git" / "hooks"

    preexisting = hooks_dir / "pre-push"
    preexisting.write_text('#!/bin/sh\nread line; echo "legacy-pre-push:$line"\n')
    preexisting.chmod(0o755)

    _make_policy(repo, "first", ["main"])
    _make_policy(repo, "second", ["release"])
    for policy_id in ("first", "second"):
        compile_policy(
            repo / ".agents" / "policies" / policy_id,
            targets=[Surface.GIT_HOOK.value],
            output_root=repo / ".chock" / "compiled",
        )

    assert install_main([str(repo)]) == 0

    dispatcher = hooks_dir / "pre-push"
    assert dispatcher.exists()
    dispatcher_text = dispatcher.read_text()
    assert 'HOOK_DIR="$(cd "$(dirname "$0")" && pwd)"' in dispatcher_text

    relocated = hooks_dir / "pre-push.d" / "00-preexisting"
    assert relocated.exists()
    assert "legacy-pre-push" in relocated.read_text()

    wrappers = sorted((hooks_dir / "pre-push.d").glob("50-chock-policy-*"))
    assert len(wrappers) == 2

    ref_line = "refs/heads/feat/ABC-123-demo abc123 refs/heads/feat/ABC-123-demo def456\n"
    result = subprocess.run(
        ["sh", str(dispatcher)],
        cwd=repo,
        input=ref_line,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "legacy-pre-push:" in result.stdout
    assert ref_line.strip() in result.stdout
