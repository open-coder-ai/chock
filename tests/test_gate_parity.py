"""Parity tests: new declarative runner must match old shell-script decisions for baselines."""

from __future__ import annotations

import subprocess
from pathlib import Path

from conftest import baseline_policy, build_test_gate_json, init_repo, stage

from chock.gate.runner import run

SCAN_SECRETS_DIR = baseline_policy("scan-secrets")
PROTECT_MAIN_BRANCH_DIR = baseline_policy("protect-main-branch")


def _scan_gate(tmp_path: Path) -> Path:
    return build_test_gate_json(tmp_path, SCAN_SECRETS_DIR)


def _protect_gate(tmp_path: Path) -> Path:
    return build_test_gate_json(tmp_path, PROTECT_MAIN_BRANCH_DIR)


class TestScanSecretsParity:
    def test_aws_access_key_blocked(self, tmp_path: Path) -> None:
        """tc-001: AWS access key ID in a staged file blocks."""
        init_repo(tmp_path)
        stage(tmp_path, "app.py", 'KEY = "AKIAIOSFODNN7EXAMPLE"\n')
        assert run(_scan_gate(tmp_path), "pre-commit", None, tmp_path) == 1

    def test_env_file_blocked(self, tmp_path: Path) -> None:
        """tc-002: a .env file blocks."""
        init_repo(tmp_path)
        stage(tmp_path, ".env", "SECRET=foo\n")
        assert run(_scan_gate(tmp_path), "pre-commit", None, tmp_path) == 1

    def test_password_word_without_secret_allows(self, tmp_path: Path) -> None:
        """tc-003: the word 'password' in a comment with no secret value allows."""
        init_repo(tmp_path)
        stage(tmp_path, "app.py", "// this input is a password field\n")
        assert run(_scan_gate(tmp_path), "pre-commit", None, tmp_path) == 0

    def test_allowlisted_fixture_allows(self, tmp_path: Path) -> None:
        """tc-004: a fake secret with the allowlist pragma on the same line allows."""
        init_repo(tmp_path)
        stage(tmp_path, "fixture.py", 'KEY = "AKIAIOSFODNN7EXAMPLE"  # pragma: allowlist secret\n')
        assert run(_scan_gate(tmp_path), "pre-commit", None, tmp_path) == 0


class TestProtectMainBranchParity:
    def test_commit_on_main_blocked(self, tmp_path: Path) -> None:
        """tc-001: a commit on main blocks."""
        repo = init_repo(tmp_path)
        subprocess.run(["git", "checkout", "-b", "main"], cwd=repo, check=True)
        stage(repo, "a.txt", "ok\n")
        assert run(_protect_gate(tmp_path), "pre-commit", None, repo) == 1

    def test_push_to_main_blocked(self, tmp_path: Path) -> None:
        """tc-002: pushing refs/heads/main blocks."""
        init_repo(tmp_path)
        stdin = "refs/heads/main abc refs/heads/main def\n"
        assert run(_protect_gate(tmp_path), "pre-push", stdin, tmp_path) == 1

    def test_commit_on_feature_allows(self, tmp_path: Path) -> None:
        """tc-003: a commit on a feature branch allows."""
        repo = init_repo(tmp_path)
        subprocess.run(["git", "checkout", "-b", "feature"], cwd=repo, check=True)
        stage(repo, "a.txt", "ok\n")
        assert run(_protect_gate(tmp_path), "pre-commit", None, repo) == 0

    def test_push_to_feature_main_menu_allows(self, tmp_path: Path) -> None:
        """tc-004: pushing a non-protected ref like feature/main-menu allows."""
        init_repo(tmp_path)
        stdin = "refs/heads/feature/main-menu abc refs/heads/feature/main-menu def\n"
        assert run(_protect_gate(tmp_path), "pre-push", stdin, tmp_path) == 0
