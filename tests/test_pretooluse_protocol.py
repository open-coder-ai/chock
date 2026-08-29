"""The vendored runtimes' wire protocol: what each client sends in, how a deny comes back.

Every vendor-specific claim pinned here traces to agentseam's own live-verified adapters
(`gate/runtime_bundle.py` bundles them with chock's guard-running handler spliced in) --
this file exercises the RENDERED, self-contained files exactly as `.chock/bin/` ships
them, not the adapter modules directly, so a regression in the splice itself would show up
here too. A break in this file means a shipped runtime still LOOKS like it enforces while
allowing every command -- the failure this project exists to refuse.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import baseline_policy

from chock.gate import runtime_bundle

GUARD = baseline_policy("block-destructive-commands") / "implementations" / "block-destructive.sh"


@pytest.fixture(scope="module")
def runtimes(tmp_path_factory) -> dict[str, Path]:
    """Each agent's rendered runtime, written once and reused across this file's tests."""
    out = tmp_path_factory.mktemp("runtimes")
    paths = {}
    for agent in runtime_bundle.RUNTIME_AGENTS:
        path = out / f"{agent}.py"
        path.write_text(runtime_bundle.render(agent), encoding="utf-8")
        paths[agent] = path
    return paths


def _run(runtimes: dict[str, Path], agent: str, payload: bytes, guard: Path = GUARD) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(runtimes[agent]), "--guard", str(guard)], input=payload, capture_output=True
    )


def test_a_silent_guard_still_gives_a_deny_reason(tmp_path: Path, runtimes) -> None:
    """A guard that denies with empty output must not become a silent ALLOW.

    Codex records a PreToolUse hook that exits 2 without writing a reason to stderr as a
    FAILED hook ("did not write a blocking reason to stderr",
    codex-rs/hooks/src/events/pre_tool_use.rs) and lets the command run -- moot for the
    codex_cli runtime specifically (it never uses the exit-2 channel at all, see below),
    but the underlying guard-running logic (`gate/guard_runner.py`, shared by every
    runtime) supplies a fallback reason regardless of which vendor is asking.
    """
    silent = tmp_path / "silent-guard.sh"
    silent.write_text("#!/usr/bin/env bash\nexit 1\n", encoding="utf-8")

    payload = json.dumps(
        {
            "tool_name": "Bash",
            "tool_input": {"command": "rm -rf /"},
            "hook_event_name": "PreToolUse",
            "session_id": "s",
            "transcript_path": "/t",
            "permission_mode": "default",
        }
    ).encode("utf-8")
    result = _run(runtimes, "claude_code", payload, guard=silent)

    assert result.returncode == 0
    stderr = result.stderr.decode("utf-8", "replace")
    assert stderr.strip(), "a deny with no reason must still be explained on stderr"
    assert "silent-guard.sh" in stderr, "the reason names the guard that denied"
    decision = json.loads(result.stdout.decode("utf-8"))
    assert decision["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert decision["hookSpecificOutput"]["permissionDecisionReason"], "a deny with no reason is a Codex FAILED hook"


def test_a_utf8_bom_payload_is_still_checked(runtimes) -> None:
    """Cursor prefixes its hook payload with a UTF-8 BOM. It must not disable the guard.

    Witnessed failing on a real Cursor install: `sys.stdin.read()` decoded the bytes with
    the Windows locale (cp1252), turning the BOM into 'i>>¿', json.loads raised, and the
    old adapter reported "not checked" and returned 0 -- so EVERY command was allowed
    while the package advertised enforcement. Bytes in, utf-8-sig out -- now agentseam's
    own stdin decoding (`_read_payload` in every bundle), not chock's.
    """
    payload = b"\xef\xbb\xbf" + json.dumps(
        {"conversation_id": "abc", "model": "grok-4.6", "command": "rm -rf /", "cwd": "/x", "sandbox": False}
    ).encode("utf-8")

    result = _run(runtimes, "cursor", payload)

    assert result.returncode == 0
    assert b"BLOCKED" in result.stderr, "a BOM must not turn a deny into an unchecked allow"
    decision = json.loads(result.stdout.decode("utf-8"))
    assert decision["permission"] == "deny"


def test_non_ascii_in_a_command_is_not_mangled(runtimes) -> None:
    """The same locale-decoding bug would corrupt any non-ASCII path a command carries."""
    payload = json.dumps({"command": "rm -rf /tmp/café-日本", "cwd": "."}).encode("utf-8")

    result = _run(runtimes, "cursor", payload)

    decision = json.loads(result.stdout.decode("utf-8"))
    assert decision["permission"] == "deny", "a non-ASCII target must still be evaluated"


def test_cursor_deny_speaks_cursors_dialect(runtimes) -> None:
    """Cursor's `permission` shape, not Claude's `hookSpecificOutput`."""
    payload = json.dumps({"command": "rm -rf /", "cwd": "/x", "sandbox": False}).encode("utf-8")

    result = _run(runtimes, "cursor", payload)

    assert result.returncode == 0
    decision = json.loads(result.stdout.decode("utf-8"))
    assert decision["permission"] == "deny"
    assert decision["user_message"], "a denial must say why"
    assert decision["agent_message"], "the agent needs the reason too"


def test_each_client_gets_only_its_own_deny_dialect(runtimes) -> None:
    """One dialect per client, never another's -- and agentseam's own verified exit-code
    posture per vendor (see each adapter's `respond()` docstring for why)."""
    codex = _run(
        runtimes,
        "codex_cli",
        json.dumps(
            {
                "turn_id": "t",
                "tool_name": "Bash",
                "tool_input": {"command": "rm -rf /"},
                "hook_event_name": "PreToolUse",
            }
        ).encode("utf-8"),
    )
    claude = _run(
        runtimes,
        "claude_code",
        json.dumps(
            {
                "tool_name": "Bash",
                "tool_input": {"command": "rm -rf /"},
                "hook_event_name": "PreToolUse",
                "session_id": "s",
                "transcript_path": "/t",
                "permission_mode": "default",
            }
        ).encode("utf-8"),
    )
    copilot = _run(
        runtimes,
        "vscode_copilot",
        json.dumps(
            {
                "tool_name": "Bash",
                "tool_input": {"command": "rm -rf /"},
                "hook_event_name": "PreToolUse",
                "timestamp": "2026-08-29T00:00:00Z",
            }
        ).encode("utf-8"),
    )
    cursor = _run(runtimes, "cursor", json.dumps({"command": "rm -rf /", "cwd": ".", "sandbox": False}).encode("utf-8"))

    # Every one of agentseam's adapters carries its verdict entirely in the JSON body, on
    # a clean exit -- verified per vendor (see e.g. claude_code.respond()'s docstring on
    # why exit 2 is deliberately NOT used: it collapses to 1 under a PowerShell wrapper on
    # some vendors, and leaks the command line into the UI where the JSON form does not).
    for result in (claude, copilot, cursor, codex):
        assert result.returncode == 0

    codex_out = json.loads(codex.stdout.decode("utf-8"))
    assert codex_out["hookSpecificOutput"]["permissionDecision"] == "deny"

    claude_out = json.loads(claude.stdout.decode("utf-8"))
    assert claude_out["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "permission" not in claude_out, "Cursor's key must not appear here"

    copilot_out = json.loads(copilot.stdout.decode("utf-8"))
    assert copilot_out["hookSpecificOutput"]["permissionDecision"] == "deny"

    cursor_out = json.loads(cursor.stdout.decode("utf-8"))
    assert cursor_out["permission"] == "deny"
    assert "hookSpecificOutput" not in cursor_out, "Claude's key must not appear here"


def test_a_cursor_allow_is_explicit(runtimes) -> None:
    """Unlike Claude Code's silent allow, Cursor's beforeShellExecution always answers
    with an explicit `permission` -- verified against Cursor's own hooks documentation
    (see agentseam's `cursor.py` adapter); a stray silence there is what would be
    ambiguous for this gate, not the reverse."""
    payload = json.dumps({"command": "ls -la", "cwd": ".", "sandbox": False}).encode("utf-8")

    result = _run(runtimes, "cursor", payload)

    assert result.returncode == 0
    decision = json.loads(result.stdout.decode("utf-8"))
    assert decision == {"permission": "allow"}
