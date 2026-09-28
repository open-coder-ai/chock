"""A plugin's hook starts its runtime through the shipped launcher, not a bare `python3`.

On Windows `python3` is often missing or the Store stub (it exists and exits 9009): the hook
then failed to start, and Claude Code let the command run. git's own sh runs the launcher,
which picks the first Python 3.11+ that actually runs, or refuses with exit 2.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

import pytest
import yaml
from conftest import baseline_policy, run_hook_command

from chock.hooks.launch import launcher_text
from chock.plugin.claude import build_claude_plugin

posix_only = pytest.mark.skipif(sys.platform == "win32", reason="symlinked PATH shims are a POSIX construct")

POLICY_ID = "block-destructive-commands"
RM_ROOT = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": "rm -rf /"}}


def _plugin(tmp_path: Path) -> tuple[Path, str]:
    """A built Claude Code plugin and its PreToolUse command, the root token expanded as the client does."""
    pack = baseline_policy(POLICY_ID)
    manifest = yaml.safe_load((pack / "manifest.yaml").read_text(encoding="utf-8"))
    out = tmp_path / "plugin"
    build_claude_plugin(pack, manifest, tmp_path, out)
    hooks = json.loads((out / "hooks" / "hooks.json").read_text(encoding="utf-8"))
    command = hooks["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
    return out, command.replace("${CLAUDE_PLUGIN_ROOT}", out.as_posix())


def _bin(tmp_path: Path, *tools: str, **links: str) -> Path:
    """A PATH directory holding `tools` from this machine plus `links` (name -> target)."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for tool in tools:
        found = shutil.which(tool)
        assert found, tool
        (bin_dir / tool).symlink_to(found)
    for name, target in links.items():
        (bin_dir / name).symlink_to(target)
    return bin_dir


def _stub(bin_dir: Path, name: str) -> None:
    """A `name` on PATH that exists but does not run, like Windows' python3 Store alias."""
    stub = bin_dir / name
    stub.write_text("#!/bin/sh\nexit 9009\n", encoding="utf-8")
    stub.chmod(0o755)


def test_the_plugin_ships_the_launcher_beside_its_runtime(tmp_path: Path) -> None:
    out, command = _plugin(tmp_path)
    assert (out / "scripts" / "launch.sh").read_text(encoding="utf-8") == launcher_text()
    assert not command.startswith("python3"), "a bare python3 is what failed open on Windows"


@posix_only
def test_a_python3_that_does_not_run_is_skipped_and_the_guard_still_denies(tmp_path: Path) -> None:
    _out, command = _plugin(tmp_path)
    shims = _bin(tmp_path, python=sys.executable)
    _stub(shims, "python3")
    env = {**os.environ, "PATH": f"{shims}{os.pathsep}{os.environ['PATH']}"}
    outside = tmp_path / "not-a-repo"
    outside.mkdir()
    proc = run_hook_command(command, outside, json.dumps(RM_ROOT), env=env)
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout)["hookSpecificOutput"]["permissionDecision"] == "deny"


@posix_only
def test_no_working_python_refuses_rather_than_failing_open(tmp_path: Path) -> None:
    _out, command = _plugin(tmp_path)
    bin_dir = _bin(tmp_path, "git", "sh", "bash")
    _stub(bin_dir, "python3")
    proc = run_hook_command(command, tmp_path, json.dumps(RM_ROOT), env={"PATH": str(bin_dir)})
    assert proc.returncode == 2, "exit 2 blocks; the Store stub's 9009 was a non-blocking error"
    assert "no working Python" in proc.stderr
