"""The built-in protection also covers a session's binding to the toggle files it saw (F17)."""

from __future__ import annotations

from pathlib import Path

import pytest
from test_guardrails_protect import _gate, _guard

BINDING = "~/.chock/state/guardrails-session-x.json"


@pytest.mark.parametrize(
    "command",
    [
        f"echo '{{}}' > {BINDING}",
        f"cp /tmp/forged.json {BINDING}",
        f"rm {BINDING}",
        "tee ~/.chock/state/guardrails-session-abc-1.json < forged",
        "echo '{}' > ~/.chock/state/guardrails-session-*.json",
        "echo '{}' > ~/.chock/state/guardrails-s*.json",
        f"python3 -c 'import os' && echo {BINDING}",
    ],
)
def test_the_shell_guard_refuses_a_write_to_a_session_binding(tmp_path: Path, command: str) -> None:
    proc = _guard(command, tmp_path)
    assert proc.returncode == 1, (proc.stdout, proc.stderr)


@pytest.mark.parametrize(
    "command", [f"cat {BINDING}", f"grep on {BINDING}", "ls ~/.chock/state", "echo hi > notes.txt"]
)
def test_the_shell_guard_lets_reads_through(tmp_path: Path, command: str) -> None:
    assert _guard(command, tmp_path).returncode == 0


@pytest.mark.parametrize(
    "path",
    [
        "/home/someone/.chock/state/guardrails-session-x.json",
        ".chock/state/guardrails-session-abc.json",
        ".CHOCK/STATE/Guardrails-Session-1.json",
        "C:\\Users\\someone\\.chock\\state\\guardrails-session-1.json",
    ],
)
def test_the_write_gate_refuses_a_session_binding(tmp_path: Path, path: str) -> None:
    proc = _gate({path: "{}"}, tmp_path)
    assert proc.returncode == 1 and "guardrails toggle file" in proc.stderr


def test_the_write_gate_follows_a_link_and_passes_other_state_files(tmp_path: Path) -> None:
    state = tmp_path / ".chock" / "state"
    state.mkdir(parents=True)
    (state / "guardrails-session-x.json").write_text("{}", encoding="utf-8")
    (tmp_path / "alias.json").symlink_to(state / "guardrails-session-x.json")
    assert _gate({"alias.json": "{}"}, tmp_path).returncode == 1
    assert _gate({".chock/state/abc.jsonl": "x", ".chock/state/guardrails.md": "x"}, tmp_path).returncode == 0
