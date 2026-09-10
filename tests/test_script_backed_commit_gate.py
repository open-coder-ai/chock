"""A policy whose check needs more than a regex over the diff ships a script; the hook runs it."""

from __future__ import annotations

import subprocess
from pathlib import Path

import yaml
from conftest import baseline_policy

from chock.compile.compiler import compile_policy
from chock.compile.surfaces import Surface
from chock.eval.suites import Policy

POLICY_ID = "refuse-erasure"

_GUARD = '''#!/usr/bin/env python3
"""Refuse a staged change that deletes the marker; argv is empty, git is the input."""

import subprocess
import sys

staged = subprocess.run(
    ["git", "diff", "--cached", "--name-only"], capture_output=True, text=True, check=False
).stdout.split()
for path in staged:
    before = subprocess.run(["git", "show", f"HEAD:{path}"], capture_output=True, text=True, check=False).stdout
    after = subprocess.run(["git", "show", f":{path}"], capture_output=True, text=True, check=False).stdout
    if "MARKER" in before and "MARKER" not in after:
        print(f"{path}: the marker was erased", file=sys.stderr)
        raise SystemExit(1)
raise SystemExit(0)
'''

_MANIFEST = {
    "id": POLICY_ID,
    "name": "Refuse Erasure",
    "version": "0.0.1",
    "description": "trigger: editing marked files. avoid: erasing the marker.",
    "artifact": "hook",
    "enforcement": "block",
    "rule": {"text": "never(erase): MARKER\n"},
}


def _policy(tmp_path: Path, name: str, body: str = _GUARD) -> Path:
    policy_dir = tmp_path / ".agents" / "policies" / POLICY_ID
    (policy_dir / "implementations").mkdir(parents=True)
    (policy_dir / "manifest.yaml").write_text(yaml.safe_dump(_MANIFEST), encoding="utf-8")
    guard = policy_dir / "implementations" / name
    guard.write_text(body, encoding="utf-8")
    guard.chmod(0o755)
    return policy_dir


def test_a_script_backed_policy_emits_a_pre_commit_shim(tmp_path: Path) -> None:
    """Without this branch the emitter returns [] and the guard is never wired to any event."""
    policy_dir = _policy(tmp_path, f"{POLICY_ID}-pre-commit.py")
    output_root = tmp_path / ".chock" / "compiled"

    compile_policy(policy_dir, targets=[Surface.GIT_HOOK.value], output_root=output_root)

    shim = output_root / POLICY_ID / "git-hook" / "git-pre-commit.sh"
    assert shim.exists(), "a policy shipping a pre-commit script emitted no hook"
    text = shim.read_text(encoding="utf-8")
    assert f".agents/policies/{POLICY_ID}/implementations/{POLICY_ID}-pre-commit.py" in text
    assert not (output_root / POLICY_ID / "git-hook" / "gate.json").exists()


def test_the_installer_name_is_the_one_it_discovers(tmp_path: Path) -> None:
    """The installer globs `*/git-hook/git-pre-commit.sh`; a different name installs nothing."""
    from chock.hooks.installers import _discover_policy_hooks

    policy_dir = _policy(tmp_path, f"{POLICY_ID}-pre-commit.py")
    compile_policy(policy_dir, targets=[Surface.GIT_HOOK.value], output_root=tmp_path / ".chock" / "compiled")

    assert [p.name for p in _discover_policy_hooks(tmp_path, "git-pre-commit.sh")] == ["git-pre-commit.sh"]


def test_a_declarative_gate_still_wins(tmp_path: Path) -> None:
    """The script branch is a fallback; a declarative policy must keep emitting gate.json."""
    output_root = tmp_path / ".chock" / "compiled"
    compile_policy(baseline_policy("protect-main-branch"), targets=[Surface.GIT_HOOK.value], output_root=output_root)

    git_hook_dir = output_root / "protect-main-branch" / "git-hook"
    assert (git_hook_dir / "gate.json").exists()
    assert '.chock/bin/gate.py" run' in (git_hook_dir / "git-pre-commit.sh").read_text(encoding="utf-8")


def test_an_unrelated_policy_emits_nothing(tmp_path: Path) -> None:
    """A rule-only policy must not gain a hook: the fallback keys off the script's name."""
    policy_dir = _policy(tmp_path, f"{POLICY_ID}.py")  # a command guard, not an event script
    output_root = tmp_path / ".chock" / "compiled"

    compile_policy(policy_dir, targets=[Surface.GIT_HOOK.value], output_root=output_root)

    assert not (output_root / POLICY_ID / "git-hook").exists()


def test_an_event_script_is_not_an_eval_command_guard(tmp_path: Path) -> None:
    """Fed an eval case's argv it would exit 0 and score a verdict it never gave."""
    policy_dir = _policy(tmp_path, f"{POLICY_ID}-pre-commit.py")
    suite = Policy(POLICY_ID, policy_dir, _MANIFEST)

    assert suite.guards == []
    assert not suite.deterministic


def test_the_shim_runs_the_guard_and_the_guard_refuses(tmp_path: Path) -> None:
    """End to end in a real repo: the emitted shim blocks the staged erasure and allows the rest."""
    policy_dir = _policy(tmp_path, f"{POLICY_ID}-pre-commit.py")
    compile_policy(policy_dir, targets=[Surface.GIT_HOOK.value], output_root=tmp_path / ".chock" / "compiled")
    shim = tmp_path / ".chock" / "compiled" / POLICY_ID / "git-hook" / "git-pre-commit.sh"

    def git(*args: str) -> None:
        subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)

    git("init", "-q")
    git("config", "user.email", "t@example.invalid")
    git("config", "user.name", "t")
    page = tmp_path / "page.txt"
    page.write_text("MARKER stays\n", encoding="utf-8")
    git("add", "page.txt")
    git("commit", "-qm", "base")

    page.write_text("MARKER stays, and more\n", encoding="utf-8")
    git("add", "page.txt")
    assert subprocess.run(["bash", str(shim)], cwd=tmp_path, capture_output=True).returncode == 0

    page.write_text("erased\n", encoding="utf-8")
    git("add", "page.txt")
    refused = subprocess.run(["bash", str(shim)], cwd=tmp_path, capture_output=True, text=True)
    assert refused.returncode == 1
    assert "the marker was erased" in refused.stderr


def test_a_missing_guard_fails_closed(tmp_path: Path) -> None:
    """A shim whose guard was deleted must refuse, not wave the commit through."""
    policy_dir = _policy(tmp_path, f"{POLICY_ID}-pre-commit.py")
    compile_policy(policy_dir, targets=[Surface.GIT_HOOK.value], output_root=tmp_path / ".chock" / "compiled")
    shim = tmp_path / ".chock" / "compiled" / POLICY_ID / "git-hook" / "git-pre-commit.sh"
    (policy_dir / "implementations" / f"{POLICY_ID}-pre-commit.py").unlink()

    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True, capture_output=True)
    result = subprocess.run(["bash", str(shim)], cwd=tmp_path, capture_output=True, text=True)
    assert result.returncode == 2
    assert "ships no guard" in result.stderr
