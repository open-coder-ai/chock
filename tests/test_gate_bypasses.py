"""Regressions for the gate-runner bypasses found in the 2026-08 full-repo audit."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from conftest import init_repo, stage, write_gate

from chock.gate.runner import run

SECRET_PARAMS = {
    "scan": "added_lines",
    "allowlist_pragma": r"#\s*pragma:\s*allowlist\s+secret",
    "content_pattern": r"(?i)(AKIA[0-9A-Z]{16})",
}
AWS_KEY = 'KEY = "AKIAIOSFODNN7EXAMPLE"\n'  # pragma: allowlist secret  (documented AWS test fixture)


def _secret_gate(tmp_path: Path) -> Path:
    return write_gate(
        tmp_path,
        {"kind": "content_regex", "on": ["commit"], "action": "block", "message": "secret", "params": SECRET_PARAMS},
    )


def _commit(tmp_path: Path, msg: str = "seed") -> None:
    subprocess.run(["git", "commit", "-q", "-m", msg], cwd=tmp_path, check=True)


def test_renamed_and_edited_file_is_scanned(tmp_path: Path) -> None:
    init_repo(tmp_path)
    stage(tmp_path, "notes.txt", "just notes\n")
    _commit(tmp_path)
    subprocess.run(["git", "mv", "notes.txt", "config.txt"], cwd=tmp_path, check=True)
    (tmp_path / "config.txt").write_text("just notes\n" + AWS_KEY, encoding="utf-8")
    subprocess.run(["git", "add", "config.txt"], cwd=tmp_path, check=True)
    assert run(_secret_gate(tmp_path), "pre-commit", None, tmp_path) == 1


def test_non_ascii_filename_is_scanned(tmp_path: Path) -> None:
    init_repo(tmp_path)
    stage(tmp_path, "sécrets.txt", AWS_KEY)
    assert run(_secret_gate(tmp_path), "pre-commit", None, tmp_path) == 1


def test_nested_manifest_dependency_is_scanned(tmp_path: Path) -> None:
    init_repo(tmp_path)
    (tmp_path / "allow.txt").write_text("react\n", encoding="utf-8")
    gate = write_gate(
        tmp_path,
        {
            "kind": "dependency_allowlist",
            "on": ["commit"],
            "action": "block",
            "message": "unlisted dep",
            "params": {"manifests": ["package.json"], "allowlist_file": "allow.txt"},
        },
    )
    stage(tmp_path, "web/package.json", '{"dependencies": {"react": "18", "evil-pkg": "1"}}\n')
    assert run(gate, "pre-commit", None, tmp_path) == 1


def test_root_manifest_still_scanned(tmp_path: Path) -> None:
    init_repo(tmp_path)
    (tmp_path / "allow.txt").write_text("react\n", encoding="utf-8")
    gate = write_gate(
        tmp_path,
        {
            "kind": "dependency_allowlist",
            "on": ["commit"],
            "action": "block",
            "message": "unlisted dep",
            "params": {"manifests": ["package.json"], "allowlist_file": "allow.txt"},
        },
    )
    stage(tmp_path, "package.json", '{"dependencies": {"react": "18"}}\n')
    assert run(gate, "pre-commit", None, tmp_path) == 0


def test_ci_fails_closed_on_missing_base(tmp_path: Path, capsys) -> None:
    init_repo(tmp_path)
    stage(tmp_path, "app.py", "x = 1\n")
    _commit(tmp_path)
    rc = run(_secret_gate(tmp_path), "ci", None, tmp_path, base="origin/does-not-exist")
    assert rc == 2
    assert "does not resolve" in capsys.readouterr().err


def test_ci_scans_a_valid_base(tmp_path: Path) -> None:
    init_repo(tmp_path)
    stage(tmp_path, "app.py", "x = 1\n")
    _commit(tmp_path, "base")
    base = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=tmp_path, capture_output=True, text=True, check=True
    ).stdout.strip()
    stage(tmp_path, "leak.py", AWS_KEY)
    _commit(tmp_path, "leak")
    assert run(_secret_gate(tmp_path), "ci", None, tmp_path, base=base) == 1


def test_merge_commit_installs_a_pre_merge_commit_dispatcher(tmp_path: Path) -> None:
    from chock.hooks.installers import get_hooks_dir, install_policy_hooks

    init_repo(tmp_path)
    compiled = tmp_path / ".chock" / "compiled" / "p" / "git-hook"
    compiled.mkdir(parents=True)
    (compiled / "git-pre-commit.sh").write_text("#!/bin/bash\nexit 0\n", encoding="utf-8")
    install_policy_hooks(tmp_path, get_hooks_dir(tmp_path))
    hooks = get_hooks_dir(tmp_path)
    assert (hooks / "pre-merge-commit").exists(), "merges bypass gates without this dispatcher"
    assert list((hooks / "pre-merge-commit.d").glob("50-chock-policy-*"))


@pytest.mark.parametrize("event", ["pre-commit", "pre-merge-commit"])
def test_dispatcher_runs_commit_fragments(tmp_path: Path, event: str) -> None:
    from chock.hooks.installers import get_hooks_dir, install_policy_hooks

    init_repo(tmp_path)
    compiled = tmp_path / ".chock" / "compiled" / "p" / "git-hook"
    compiled.mkdir(parents=True)
    (compiled / "git-pre-commit.sh").write_text("#!/bin/bash\nexit 0\n", encoding="utf-8")
    install_policy_hooks(tmp_path, get_hooks_dir(tmp_path))
    assert (get_hooks_dir(tmp_path) / event).exists()
