"""A script-backed hook may run at commit-msg: git hands it the message file, its exit code decides."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
import yaml

from chock.compile.compiler import compile_policy
from chock.compile.emitters.git_hook import declared_script_events
from chock.compile.surfaces import Surface
from chock.eval.suites import Policy
from chock.hooks.installers import get_hooks_dir, install_policy_hooks
from chock.validation.checks_script_events import check_script_events
from chock.validation.report import Report

POLICY_ID = "clean-messages"

_SCRIPT = '''#!/usr/bin/env python3
"""Refuse a commit message that says WIP; argv[1] is the message file."""

import sys
from pathlib import Path

if len(sys.argv) != 2:
    print("expected the message file as argv[1]", file=sys.stderr)
    raise SystemExit(2)
if "WIP" in Path(sys.argv[1]).read_text(encoding="utf-8"):
    print("commit message says WIP", file=sys.stderr)
    raise SystemExit(1)
raise SystemExit(0)
'''

_MANIFEST = {
    "id": POLICY_ID,
    "name": "Clean Messages",
    "version": "0.0.1",
    "description": "trigger: writing a commit message. avoid: WIP.",
    "artifact": "rule",
    "enforcement": "block",
    "rule": {"text": "never(commit_message): WIP\n"},
    "hook": {"script": {"on": ["commit-msg"]}},
    "provenance": {"author": "t"},
    "lifecycle": {"status": "draft"},
}


def _policy(repo: Path, manifest: dict | None = None, *, script: bool = True) -> Path:
    policy = repo / ".agents" / "policies" / POLICY_ID
    (policy / "implementations").mkdir(parents=True)
    (policy / "manifest.yaml").write_text(yaml.safe_dump(manifest or _MANIFEST), encoding="utf-8")
    if script:
        (policy / "implementations" / f"{POLICY_ID}-commit-msg.py").write_text(_SCRIPT, encoding="utf-8")
    return policy


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=repo, check=check, capture_output=True, text=True)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@example.invalid")
    _git(root, "config", "user.name", "t")
    return root


def test_the_declared_event_is_wired(repo: Path) -> None:
    assert declared_script_events(_MANIFEST) == ["commit-msg"]
    policy = _policy(repo)
    compile_policy(policy, targets=[Surface.GIT_HOOK.value], output_root=repo / ".chock" / "compiled")

    shim = repo / ".chock" / "compiled" / POLICY_ID / "git-hook" / "git-commit-msg.sh"
    text = shim.read_text(encoding="utf-8")
    assert f"implementations/{POLICY_ID}-commit-msg.py" in text
    assert '"$guard" "$@"' in text, "the message file path must reach the script"


def test_the_pre_commit_shim_still_takes_no_argument(repo: Path) -> None:
    manifest = {**_MANIFEST, "hook": {"script": {"on": ["commit"]}}}
    policy = _policy(repo, manifest, script=False)
    (policy / "implementations" / f"{POLICY_ID}-pre-commit.py").write_text(_SCRIPT, encoding="utf-8")
    compile_policy(policy, targets=[Surface.GIT_HOOK.value], output_root=repo / ".chock" / "compiled")

    text = (repo / ".chock" / "compiled" / POLICY_ID / "git-hook" / "git-pre-commit.sh").read_text(encoding="utf-8")
    assert '"$@"' not in text


def test_git_commit_is_blocked_or_allowed_by_the_script_exit_code(repo: Path) -> None:
    compile_policy(_policy(repo), targets=[Surface.GIT_HOOK.value], output_root=repo / ".chock" / "compiled")
    install_policy_hooks(repo, get_hooks_dir(repo))
    hooks_dir = get_hooks_dir(repo)
    assert (hooks_dir / "commit-msg").exists()
    assert list((hooks_dir / "commit-msg.d").glob("50-chock-policy-*"))
    (repo / "a.txt").write_text("a\n", encoding="utf-8")
    _git(repo, "add", "a.txt")

    refused = _git(repo, "commit", "-m", "WIP: half done", check=False)
    assert refused.returncode != 0
    assert "commit message says WIP" in refused.stderr
    assert _git(repo, "rev-parse", "--verify", "HEAD", check=False).returncode != 0, "nothing was committed"

    allowed = _git(repo, "commit", "-m", "add a.txt", check=False)
    assert allowed.returncode == 0, allowed.stderr
    assert _git(repo, "log", "-1", "--format=%s").stdout.strip() == "add a.txt"


def _findings(policy: Path, manifest: dict) -> list[str]:
    report = Report()
    check_script_events(policy, manifest, "rule", report)
    return [f.message for f in report.errors]


def test_det5_a_declared_commit_msg_needs_a_script(repo: Path) -> None:
    findings = _findings(_policy(repo, script=False), _MANIFEST)
    assert any("declares 'commit-msg'" in m and f"{POLICY_ID}-commit-msg" in m for m in findings), findings


def test_det5_a_commit_msg_script_needs_a_declaration(repo: Path) -> None:
    manifest = {**_MANIFEST, "hook": {"script": {"on": ["commit"]}}}
    findings = _findings(_policy(repo, manifest), manifest)
    assert any("does not declare 'commit-msg'" in m for m in findings), findings


def test_det5_declaration_and_script_agree(repo: Path) -> None:
    assert _findings(_policy(repo), _MANIFEST) == []


def test_a_commit_msg_script_is_not_an_eval_command_guard(repo: Path) -> None:
    """Fed an eval case's argv it would read a file that is not a message and score a verdict it never gave."""
    suite = Policy(POLICY_ID, _policy(repo), _MANIFEST)
    assert suite.guards == []
