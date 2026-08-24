"""The adapter's wire protocol: what each client sends in, and how a deny is spoken back.

Every case here came from a failure witnessed on a real install, not from a specification:
each vendor's documentation was either silent or wrong about the behaviour being pinned.
A break in this file means a shipped package still LOOKS like it enforces while allowing
every command -- the failure this project exists to refuse.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from conftest import baseline_policy

FRAMEWORK_ROOT = Path(__file__).resolve().parents[1]
ADAPTER = FRAMEWORK_ROOT / "src" / "chock" / "gate" / "pretooluse.py"
GUARD = baseline_policy("block-destructive-commands") / "implementations" / "block-destructive.sh"


def test_a_silent_guard_still_gives_a_deny_reason(tmp_path: Path) -> None:
    """A guard that denies with empty output must not become a silent ALLOW.

    Codex records a PreToolUse hook that exits 2 without writing a reason to stderr as a
    FAILED hook ("did not write a blocking reason to stderr",
    codex-rs/hooks/src/events/pre_tool_use.rs) and lets the command run. A guard that
    denies without explaining itself would therefore enforce nothing there while every
    other client showed a deny -- so the adapter supplies a reason when the guard gives
    none. The exit code is unaffected; only stderr gains a fallback line.
    """
    silent = tmp_path / "silent-guard.sh"
    # Exit 1 is a guard VIOLATION (GUARD_VIOLATION); the adapter translates it into
    # the client-facing deny, exit 2. This guard denies and says nothing.
    silent.write_text("#!/usr/bin/env bash\nexit 1\n", encoding="utf-8")

    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": "rm -rf /"}}).encode("utf-8")
    result = _adapter_bytes(payload, guard=silent)

    assert result.returncode == 2, "a deny is still a deny"
    stderr = result.stderr.decode("utf-8", "replace")
    assert stderr.strip(), "a deny with no reason is read as a failed hook by Codex"
    assert "silent-guard.sh" in stderr, "the reason names the guard that denied"


def _adapter_bytes(payload: bytes, guard: Path = GUARD) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(ADAPTER), "--guard", str(guard)], input=payload, capture_output=True)


def test_a_utf8_bom_payload_is_still_checked() -> None:
    """Cursor prefixes its hook payload with a UTF-8 BOM. It must not disable the guard.

    Witnessed failing on a real Cursor install: `sys.stdin.read()` decoded the bytes with
    the Windows locale (cp1252), turning the BOM into 'i>>¿', json.loads raised, and the
    adapter reported "not checked" and returned 0 -- so EVERY command was allowed while
    the package advertised enforcement. Bytes in, utf-8-sig out.
    """
    payload = b"\xef\xbb\xbf" + json.dumps(
        {"conversation_id": "abc", "model": "grok-4.6", "command": "rm -rf /", "cwd": "/x", "sandbox": False}
    ).encode("utf-8")

    result = _adapter_bytes(payload)

    assert result.returncode == 2, "a BOM must not turn a deny into an allow"
    assert b"BLOCKED" in result.stderr


def test_non_ascii_in_a_command_is_not_mangled() -> None:
    """The same locale-decoding bug would corrupt any non-ASCII path a command carries."""
    payload = json.dumps({"command": "rm -rf /tmp/café-日本", "cwd": "."}).encode("utf-8")

    result = _adapter_bytes(payload)

    assert result.returncode == 2, "a non-ASCII target must still be evaluated"


def test_cursor_deny_speaks_cursors_dialect() -> None:
    """Cursor needs the stdout JSON; exit 2 alone does not block it.

    Cursor documents exit 2 as "equivalent to returning permission: deny", but a plugin
    hook returning exit 2 with the reason on stderr was witnessed NOT blocking on a real
    install -- the command ran. The stdout response is what Cursor honours, so the
    adapter sends both. Witnessed blocking after this change.
    """
    payload = json.dumps({"command": "rm -rf /", "cwd": "/x", "sandbox": False}).encode("utf-8")

    result = _adapter_bytes(payload)

    assert result.returncode == 2
    decision = json.loads(result.stdout.decode("utf-8"))
    assert decision["permission"] == "deny"
    assert decision["user_message"], "a denial must say why"
    assert decision["agent_message"], "the agent needs the reason too"


def test_each_client_gets_only_its_own_deny_dialect() -> None:
    """One dialect per client, never another's.

    Cursor reads `permission`; Claude Code and Codex read `hookSpecificOutput`. A schema a
    client does not know is at best ignored and at worst a parse error that voids the
    verdict, so each shape must appear only where it is understood. Copilot reads the exit
    code and stderr and gets no object at all.
    """
    codex = _adapter_bytes(
        json.dumps({"turn_id": "t", "tool_name": "Bash", "tool_input": {"command": "rm -rf /"}}).encode("utf-8")
    )
    claude = _adapter_bytes(json.dumps({"tool_name": "Bash", "tool_input": {"command": "rm -rf /"}}).encode("utf-8"))
    copilot = _adapter_bytes(
        json.dumps({"toolName": "bash", "toolArgs": json.dumps({"command": "rm -rf /"})}).encode("utf-8")
    )
    cursor = _adapter_bytes(json.dumps({"command": "rm -rf /", "cwd": ".", "sandbox": False}).encode("utf-8"))

    for result in (claude, copilot, cursor):
        assert result.returncode == 2, "these clients deny via exit code 2"
    # Codex is the exception, and deliberately: its Windows shell wrapper collapses exit 2
    # into 1 (a failed hook, fail-open), and exit 0 is the only arm of its parser that
    # reads stdout JSON. Witnessed: exit 2 ran the command, exit 0 + JSON blocked it.
    assert codex.returncode == 0, "Codex denies via stdout JSON on a CLEAN exit"
    codex_out = json.loads(codex.stdout.decode("utf-8"))
    assert codex_out["hookSpecificOutput"]["permissionDecision"] == "deny"

    claude_out = json.loads(claude.stdout.decode("utf-8"))
    assert claude_out["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "permission" not in claude_out, "Cursor's key must not appear here"

    cursor_out = json.loads(cursor.stdout.decode("utf-8"))
    assert cursor_out["permission"] == "deny"
    assert "hookSpecificOutput" not in cursor_out, "Claude's key must not appear here"

    assert copilot.stdout.strip() == b"", "Copilot reads the exit code, not an object"


def test_a_cursor_allow_writes_nothing_to_stdout() -> None:
    """An allowed command must stay silent: a stray object could be read as a decision."""
    payload = json.dumps({"command": "ls -la", "cwd": ".", "sandbox": False}).encode("utf-8")

    result = _adapter_bytes(payload)

    assert result.returncode == 0
    assert result.stdout.strip() == b""
