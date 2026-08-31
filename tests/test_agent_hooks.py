"""agent-hooks surface (chock#48): the .github/hooks entry for Copilot CLI + VS Code."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import working_bash

from chock.compile.emitters.agent_hooks import SHELL_MATCHER, build_entry, emit
from chock.gate import runtime_bundle


def _payload(command: str) -> str:
    return json.dumps(
        {
            "tool_name": "Bash",
            "tool_input": {"command": command},
            "hook_event_name": "PreToolUse",
            "timestamp": "2026-08-29T00:00:00Z",
        }
    )


def _guard_body() -> str:
    return '#!/usr/bin/env bash\nset -eu\ncase "$*" in *rm*-rf*) exit 1;; esac\nexit 0\n'


def _synced_repo(tmp_path: Path) -> tuple[Path, dict]:
    """A git repo with the vendored runtime and one guard at the paths the entry references."""
    repo = tmp_path / "adopter"
    (repo / ".chock" / "bin").mkdir(parents=True)
    pol = repo / ".agents" / "policies" / "block-destructive-commands" / "implementations"
    pol.mkdir(parents=True)
    (repo / ".chock" / "bin" / "vscode_copilot.py").write_text(
        runtime_bundle.render("vscode_copilot"), encoding="utf-8"
    )
    (pol / "block-destructive.sh").write_text(_guard_body(), encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    manifest = {"id": "block-destructive-commands"}
    return repo, manifest


def test_build_entry_has_all_four_command_fields(tmp_path):
    pol = tmp_path / ".agents" / "policies" / "block-destructive-commands"
    (pol / "implementations").mkdir(parents=True)
    (pol / "implementations" / "block-destructive.sh").write_text(_guard_body(), encoding="utf-8")
    entry = build_entry(pol, {"id": "block-destructive-commands"})
    assert entry is not None
    assert set(entry) >= {"bash", "command", "powershell", "windows", "matcher", "type"}
    assert entry["bash"] == entry["command"]
    assert entry["powershell"] == entry["windows"]
    assert entry["matcher"] == SHELL_MATCHER


def test_matcher_excludes_read_tools():
    import re

    rx = re.compile(f"^(?:{SHELL_MATCHER})$")
    assert rx.match("powershell") and rx.match("bash")
    assert not rx.match("view") and not rx.match("glob")


def test_guardless_policy_emits_nothing(tmp_path):
    pol = tmp_path / "advisory-only"
    pol.mkdir()
    assert emit(pol, tmp_path / "out", {"id": "advisory-only"}) == []


@pytest.mark.skipif(
    sys.platform == "win32", reason="the bash field targets Unix; Windows clients use the powershell field"
)
def test_emitted_bash_command_denies_end_to_end(tmp_path):
    bash = working_bash()
    if not bash:
        pytest.skip("no working bash (WSL relay does not count)")
    repo, manifest = _synced_repo(tmp_path)
    entry = build_entry(Path(".agents/policies/block-destructive-commands"), manifest)
    bash_cmd = entry["bash"]

    blocked = subprocess.run(
        [bash, "-c", bash_cmd], cwd=repo, input=_payload("rm -rf /"), capture_output=True, text=True
    )
    assert blocked.returncode == 0, (blocked.stdout, blocked.stderr)
    decision = json.loads(blocked.stdout)
    assert decision["hookSpecificOutput"]["permissionDecision"] == "deny", (blocked.stdout, blocked.stderr)

    allowed = subprocess.run([bash, "-c", bash_cmd], cwd=repo, input=_payload("ls -la"), capture_output=True, text=True)
    assert allowed.returncode == 0, (allowed.stdout, allowed.stderr)
    assert allowed.stdout.strip() == "", (allowed.stdout, allowed.stderr)


def _pwsh() -> str | None:
    return shutil.which("pwsh") or shutil.which("powershell")


@pytest.mark.skipif(not _pwsh(), reason="powershell not available")
def test_emitted_powershell_command_denies_end_to_end(tmp_path):
    repo, manifest = _synced_repo(tmp_path)
    entry = build_entry(Path(".agents/policies/block-destructive-commands"), manifest)
    ps_cmd = entry["powershell"]

    blocked = subprocess.run(
        [_pwsh(), "-NoProfile", "-Command", ps_cmd],
        cwd=repo,
        input=_payload("rm -rf /"),
        capture_output=True,
        text=True,
    )
    assert blocked.returncode == 0, (blocked.stdout, blocked.stderr)
    decision = json.loads(blocked.stdout)
    assert decision["hookSpecificOutput"]["permissionDecision"] == "deny", (blocked.stdout, blocked.stderr)

    allowed = subprocess.run(
        [_pwsh(), "-NoProfile", "-Command", ps_cmd],
        cwd=repo,
        input=_payload("Get-ChildItem"),
        capture_output=True,
        text=True,
    )
    assert allowed.returncode == 0, (allowed.stdout, allowed.stderr)
    assert allowed.stdout.strip() == "", (allowed.stdout, allowed.stderr)
