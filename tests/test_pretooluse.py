"""PreToolUse enforcement: the vendored runtime, the installer, and the end-to-end path."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest
from conftest import baseline_policy

from chock.gate import runtime_bundle
from chock.gate.guard_runner import find_bash

FRAMEWORK_ROOT = Path(__file__).resolve().parents[1]
GUARD = baseline_policy("block-destructive-commands") / "implementations" / "block-destructive.sh"


@pytest.fixture(scope="module")
def claude_code_runtime(tmp_path_factory) -> Path:
    path = tmp_path_factory.mktemp("runtime") / "claude_code.py"
    path.write_text(runtime_bundle.render("claude_code"), encoding="utf-8")
    return path


def _payload(command: str) -> str:
    return json.dumps(
        {
            "tool_name": "Bash",
            "tool_input": {"command": command},
            "hook_event_name": "PreToolUse",
            "session_id": "s",
            "transcript_path": "/t",
            "permission_mode": "default",
        }
    )


def _adapter(claude_code_runtime: Path, command: str, guard: Path = GUARD) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(claude_code_runtime), "--guard", str(guard)],
        input=_payload(command),
        capture_output=True,
        text=True,
    )


def _denied(result: subprocess.CompletedProcess) -> bool:
    """Claude Code's deny rides entirely in the JSON body on a clean exit -- see"""
    if result.returncode != 0 or not result.stdout.strip():
        return False
    decision = json.loads(result.stdout)
    return decision.get("hookSpecificOutput", {}).get("permissionDecision") == "deny"


@pytest.mark.parametrize(
    "command",
    ["rm -rf /", "git push --force origin main", "git reset --hard HEAD~1"],
)
def test_dangerous_commands_block(command: str, claude_code_runtime: Path) -> None:
    result = _adapter(claude_code_runtime, command)
    assert _denied(result), f"{command!r} was allowed:\n{result.stdout}{result.stderr}"
    assert "BLOCKED" in result.stderr


@pytest.mark.parametrize("command", ["ls -la", "git push --force-with-lease origin main", "git status"])
def test_safe_commands_are_allowed(command: str, claude_code_runtime: Path) -> None:
    result = _adapter(claude_code_runtime, command)
    assert result.returncode == 0
    assert not _denied(result)


def test_argv_guard_receives_the_stdin_command(claude_code_runtime: Path) -> None:
    """The original defect: guards read argv, Claude sends JSON on stdin."""
    bash = find_bash(GUARD)
    assert bash, "no usable bash on this machine; cannot exercise the guard"
    direct = subprocess.run([bash, str(GUARD)], input=_payload("rm -rf /"), capture_output=True, text=True)
    assert direct.returncode == 0, "precondition: the bare guard ignores stdin"
    assert _denied(_adapter(claude_code_runtime, "rm -rf /")), "the runtime must bridge stdin to argv"


def test_unparseable_input_allows(claude_code_runtime: Path) -> None:
    """Failing closed here would block every Bash call on a malformed payload."""
    result = subprocess.run(
        [sys.executable, str(claude_code_runtime), "--guard", str(GUARD)],
        input="not json",
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert result.stdout.strip() == ""


def test_missing_guard_allows(tmp_path: Path, claude_code_runtime: Path) -> None:
    result = _adapter(claude_code_runtime, "rm -rf /", guard=tmp_path / "absent.sh")
    assert result.returncode == 0
    assert not _denied(result)


def test_non_command_tool_input_is_ignored(claude_code_runtime: Path) -> None:
    result = subprocess.run(
        [sys.executable, str(claude_code_runtime), "--guard", str(GUARD)],
        input=json.dumps(
            {
                "tool_name": "Read",
                "tool_input": {"file_path": "/tmp/x"},
                "hook_event_name": "PreToolUse",
                "session_id": "s",
                "transcript_path": "/t",
                "permission_mode": "default",
            }
        ),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert not _denied(result)


def _fresh_repo() -> tuple[Path, dict]:
    """A scaffolded repo holding the two policies that compile a PreToolUse guard."""
    import shutil

    repo = Path(tempfile.mkdtemp()) / "r"
    repo.mkdir()
    env = {**os.environ, "PYTHONPATH": str(FRAMEWORK_ROOT / "src")}
    subprocess.run(["git", "init", "-q", "."], cwd=repo, check=True)
    subprocess.run(
        [sys.executable, "-m", "chock.cli", "init", ".", "--skip-hooks"],
        cwd=repo,
        capture_output=True,
        env=env,
    )
    for policy_id in ("block-destructive-commands", "block-no-verify"):
        shutil.copytree(baseline_policy(policy_id), repo / ".agents" / "policies" / policy_id)
    subprocess.run(
        [sys.executable, "-m", "chock.cli", "recompile", "--skip-hooks", "--repo", str(repo)],
        cwd=repo,
        capture_output=True,
        env=env,
    )
    return repo, env


def test_install_writes_claude_settings_schema() -> None:
    from chock.hooks.pretooluse_install import install_pretooluse_hooks

    repo, env = _fresh_repo()
    subprocess.run(
        [sys.executable, "-m", "chock.cli", "recompile", "--skip-hooks", "--repo", str(repo)],
        cwd=repo,
        capture_output=True,
        env=env,
    )
    install_pretooluse_hooks(repo)

    settings = json.loads((repo / ".claude" / "settings.json").read_text(encoding="utf-8"))
    entries = settings["hooks"]["PreToolUse"]
    assert entries, "no PreToolUse entries installed"
    for entry in entries:
        assert entry["matcher"] == "Bash"
        hook = entry["hooks"][0]
        assert hook["type"] == "command"
        assert "${CLAUDE_PROJECT_DIR}" in hook["command"], "paths must survive a repo move"
    assert (repo / ".chock" / "bin" / "claude_code.py").exists()


def test_install_preserves_unrelated_settings() -> None:
    """The settings file is the adopter's; only our own entries may be rewritten."""
    from chock.hooks.pretooluse_install import install_pretooluse_hooks

    repo, env = _fresh_repo()
    settings_path = repo / ".claude" / "settings.json"
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(
        json.dumps(
            {
                "permissions": {"allow": ["Bash(ls *)"]},
                "hooks": {
                    "PreToolUse": [{"matcher": "Write", "hooks": [{"type": "command", "command": "mine.sh"}]}],
                    "PostToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "after.sh"}]}],
                },
            }
        ),
        encoding="utf-8",
    )
    subprocess.run(
        [sys.executable, "-m", "chock.cli", "recompile", "--skip-hooks", "--repo", str(repo)],
        cwd=repo,
        capture_output=True,
        env=env,
    )
    install_pretooluse_hooks(repo)

    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    assert settings["permissions"] == {"allow": ["Bash(ls *)"]}
    assert settings["hooks"]["PostToolUse"][0]["hooks"][0]["command"] == "after.sh"
    commands = [h["command"] for e in settings["hooks"]["PreToolUse"] for h in e["hooks"]]
    assert "mine.sh" in commands, "a hand-written PreToolUse hook was discarded"


def test_reinstall_is_idempotent() -> None:
    from chock.hooks.pretooluse_install import install_pretooluse_hooks

    repo, env = _fresh_repo()
    subprocess.run(
        [sys.executable, "-m", "chock.cli", "recompile", "--skip-hooks", "--repo", str(repo)],
        cwd=repo,
        capture_output=True,
        env=env,
    )
    install_pretooluse_hooks(repo)
    first = (repo / ".claude" / "settings.json").read_text(encoding="utf-8")
    install_pretooluse_hooks(repo)
    assert (repo / ".claude" / "settings.json").read_text(encoding="utf-8") == first


def test_removing_the_fragments_removes_the_hooks() -> None:
    """A disabled or deleted policy must stop enforcing."""
    import shutil as sh

    from chock.hooks.pretooluse_install import install_pretooluse_hooks

    repo, env = _fresh_repo()
    subprocess.run(
        [sys.executable, "-m", "chock.cli", "recompile", "--skip-hooks", "--repo", str(repo)],
        cwd=repo,
        capture_output=True,
        env=env,
    )
    install_pretooluse_hooks(repo)
    for path in (repo / ".chock" / "compiled").glob("*/pre-tool-use"):
        sh.rmtree(path)
    install_pretooluse_hooks(repo)

    settings = json.loads((repo / ".claude" / "settings.json").read_text(encoding="utf-8"))
    assert not settings.get("hooks", {}).get("PreToolUse")
    assert not (repo / ".chock" / "bin" / "claude_code.py").exists()


def test_end_to_end_installed_hooks_block_real_commands() -> None:
    """The acceptance test: run what Claude Code runs, from a real `install-hooks`."""
    repo, env = _fresh_repo()
    subprocess.run([sys.executable, "-m", "chock.cli", "install-hooks", "."], cwd=repo, capture_output=True, env=env)
    settings = json.loads((repo / ".claude" / "settings.json").read_text(encoding="utf-8"))
    entries = settings["hooks"]["PreToolUse"]
    env = {**env, "CLAUDE_PROJECT_DIR": str(repo)}

    def blocked(command: str) -> bool:
        for entry in entries:
            cmd = entry["hooks"][0]["command"].replace("${CLAUDE_PROJECT_DIR}", str(repo))
            proc = subprocess.run(
                cmd, cwd=repo, shell=True, env=env, capture_output=True, text=True, input=_payload(command)
            )
            if _denied(proc):
                return True
        return False

    assert blocked("rm -rf /")
    assert blocked("git push --force origin main")
    assert blocked("git commit --no-verify -m x")
    assert not blocked("git push --force-with-lease origin main")
    assert not blocked("ls -la")
