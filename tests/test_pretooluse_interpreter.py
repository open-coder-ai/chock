"""The PreToolUse guard runs through the launcher: no interpreter path is ever committed."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest
from conftest import baseline_policy, bash_executable, run_hook_command

from chock.compile.compiler import compile_policy
from chock.compile.surfaces import Surface
from chock.hooks.in_agent_install import install_hooks, installed_policy_ids
from chock.hooks.launch import hook_command, record_interpreter

FRAMEWORK_ROOT = Path(__file__).resolve().parents[1]


def _fresh_repo() -> tuple[Path, dict]:
    repo = Path(tempfile.mkdtemp()) / "r"
    repo.mkdir()
    env = {**os.environ, "PYTHONPATH": str(FRAMEWORK_ROOT / "src")}
    subprocess.run(["git", "init", "-q", "."], cwd=repo, check=True)
    subprocess.run(
        [sys.executable, "-m", "chock.cli", "init", ".", "--skip-hooks"], cwd=repo, capture_output=True, env=env
    )
    shutil.copytree(
        baseline_policy("block-destructive-commands"), repo / ".agents" / "policies" / "block-destructive-commands"
    )
    subprocess.run(
        [sys.executable, "-m", "chock.cli", "recompile", "--skip-hooks", "--repo", str(repo)],
        cwd=repo,
        capture_output=True,
        env=env,
    )
    return repo, env


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


GUARD = ".agents/policies/block-destructive-commands/implementations/block-destructive-commands.py"


def _settings_path(repo: Path) -> Path:
    return repo / ".claude" / "settings.json"


def _pre_tool_command(repo: Path) -> str:
    settings = json.loads(_settings_path(repo).read_text(encoding="utf-8"))
    return settings["hooks"]["PreToolUse"][0]["hooks"][0]["command"]


def test_compiled_fragment_is_the_launcher_form(tmp_path: Path) -> None:
    policy = baseline_policy("block-destructive-commands")
    out = tmp_path / ".chock" / "compiled"
    compile_policy(policy, targets=[Surface.PRE_TOOL_USE.value], output_root=out, agents=["claude"])
    frag = json.loads((out / "block-destructive-commands" / "pre-tool-use" / "pretooluse.json").read_text())
    assert frag["hooks"][0]["command"] == hook_command(".chock/bin/claude_code.py", "--guard", GUARD)


def test_installed_command_carries_no_interpreter_and_equals_the_compiled_fragment() -> None:
    repo, _ = _fresh_repo()
    install_hooks(repo, "claude_code")
    command = _pre_tool_command(repo)
    compiled = repo / ".chock" / "compiled" / "block-destructive-commands" / "pre-tool-use" / "pretooluse.json"
    assert command == json.loads(compiled.read_text(encoding="utf-8"))["hooks"][0]["command"]
    assert sys.executable not in command
    assert "@CHOCK_PYTHON@" not in command
    assert "${" not in command


def _only_git_and_sh(tmp_path: Path) -> str:
    """A PATH directory holding git and sh and nothing else: no python on it at all."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for tool in ("git", "sh"):
        found = shutil.which(tool)
        assert found, tool
        (bin_dir / tool).symlink_to(found)
    return str(bin_dir)


@pytest.mark.skipif(sys.platform == "win32", reason="symlinked PATH shims are a POSIX construct")
def test_guard_blocks_with_no_python_on_path_via_the_recorded_interpreter(tmp_path: Path) -> None:
    repo, _ = _fresh_repo()
    install_hooks(repo, "claude_code")
    assert record_interpreter(repo)
    env = {k: v for k, v in os.environ.items() if k != "PATH"}
    env["PATH"] = _only_git_and_sh(tmp_path)
    proc = subprocess.run(
        [bash_executable(), "-c", _pre_tool_command(repo)],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        input=_payload("rm -rf /"),
        check=False,
    )
    assert proc.returncode == 0, f"guard errored with no python on PATH:\n{proc.stdout}{proc.stderr}"
    decision = json.loads(proc.stdout)
    assert decision["hookSpecificOutput"]["permissionDecision"] == "deny", proc.stdout + proc.stderr


def test_guard_denies_from_a_nested_subdirectory() -> None:
    repo, env = _fresh_repo()
    install_hooks(repo, "claude_code")
    nested = repo / "a" / "b"
    nested.mkdir(parents=True)
    proc = run_hook_command(_pre_tool_command(repo), nested, _payload("rm -rf /"), env=env)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert json.loads(proc.stdout)["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_coverage_detection_sees_the_installed_entry() -> None:
    repo, _ = _fresh_repo()
    install_hooks(repo, "claude_code")
    assert "block-destructive-commands" in installed_policy_ids(repo, "claude_code")


def test_reinstall_on_another_machine_is_byte_identical(monkeypatch: pytest.MonkeyPatch) -> None:
    repo, _ = _fresh_repo()
    install_hooks(repo, "claude_code")
    before = _settings_path(repo).read_bytes()
    monkeypatch.setattr(sys, "executable", "/opt/elsewhere/bin/python3")
    install_hooks(repo, "claude_code")
    assert _settings_path(repo).read_bytes() == before, "a reinstall elsewhere must be a zero diff"


def _old_baked_entry(interpreter: str) -> dict:
    root = "${CLAUDE_PROJECT_DIR}"
    return {
        "matcher": "Bash",
        "hooks": [
            {
                "type": "command",
                "command": f'"{interpreter}" "{root}/.chock/bin/claude_code.py" --guard "{root}/{GUARD}"',
                "timeout": 30,
            }
        ],
    }


def test_an_old_baked_entry_is_replaced_by_the_launcher_form_and_foreign_entries_kept() -> None:
    repo, _ = _fresh_repo()
    theirs = {"matcher": "Bash", "hooks": [{"type": "command", "command": "./scripts/audit.sh"}]}
    old = _old_baked_entry("/usr/bin/python3.12")
    path = _settings_path(repo)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"hooks": {"PreToolUse": [theirs, old]}}), encoding="utf-8")
    assert "block-destructive-commands" not in installed_policy_ids(repo, "claude_code"), (
        "an old-form entry is not current: sync must rewrite it"
    )
    install_hooks(repo, "claude_code")
    entries = json.loads(path.read_text(encoding="utf-8"))["hooks"]["PreToolUse"]
    assert entries[0] == theirs, "the adopter's own entry must survive, first"
    assert len(entries) == 2, "the old entry is ours: replaced, not kept beside the new one"
    assert entries[1]["hooks"][0]["command"] == hook_command(".chock/bin/claude_code.py", "--guard", GUARD)
    assert "block-destructive-commands" in installed_policy_ids(repo, "claude_code")
