"""agent-hooks surface (chock#48): the .github/hooks entry for Copilot CLI + VS Code.

The load-bearing test is end-to-end: a real temp git repo with the vendored adapter and a
real guard, running the EMITTED command through the shell -- proving git-root discovery,
interpreter resolution, stdin passthrough and exit-2 deny all work together, not just that
the JSON has the right shape.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import working_bash

from chock.compile.emitters.agent_hooks import SHELL_MATCHER, build_entry, emit

ADAPTER_SRC = Path(__file__).resolve().parents[1] / "src" / "chock" / "gate" / "pretooluse.py"


def _payload(command: str) -> str:
    # Copilot / VS Code shape: toolArgs is a JSON string.
    return json.dumps({"toolName": "powershell", "toolArgs": json.dumps({"command": command})})


def _guard_body() -> str:
    return '#!/usr/bin/env bash\nset -eu\ncase "$*" in *rm*-rf*) exit 1;; esac\nexit 0\n'


def _synced_repo(tmp_path: Path) -> tuple[Path, dict]:
    """A git repo with the vendored adapter and one guard at the paths the entry references."""
    repo = tmp_path / "adopter"
    (repo / ".chock" / "bin").mkdir(parents=True)
    pol = repo / ".agents" / "policies" / "block-destructive-commands" / "implementations"
    pol.mkdir(parents=True)
    shutil.copy(ADAPTER_SRC, repo / ".chock" / "bin" / "pretooluse.py")
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
    # view/glob are not shell tools -- the guard must not run on them.
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
    # emitter uses repo-relative paths resolved via git rev-parse at runtime
    entry = build_entry(Path(".agents/policies/block-destructive-commands"), manifest)
    bash_cmd = entry["bash"]

    blocked = subprocess.run(
        [bash, "-c", bash_cmd], cwd=repo, input=_payload("rm -rf /"), capture_output=True, text=True
    )
    assert blocked.returncode == 2, (blocked.stdout, blocked.stderr)

    allowed = subprocess.run([bash, "-c", bash_cmd], cwd=repo, input=_payload("ls -la"), capture_output=True, text=True)
    assert allowed.returncode == 0, (allowed.stdout, allowed.stderr)


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
    assert blocked.returncode == 2, (blocked.stdout, blocked.stderr)

    allowed = subprocess.run(
        [_pwsh(), "-NoProfile", "-Command", ps_cmd],
        cwd=repo,
        input=_payload("Get-ChildItem"),
        capture_output=True,
        text=True,
    )
    assert allowed.returncode == 0, (allowed.stdout, allowed.stderr)
