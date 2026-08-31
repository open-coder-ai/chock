"""What each client actually does when the guard ran and could not decide."""

from __future__ import annotations

import json
import stat
import subprocess
import sys
from pathlib import Path

import pytest
from agentseam import contract as _contract

from chock.gate import guard_runner, runtime_bundle


@pytest.fixture(scope="module")
def runtimes(tmp_path_factory) -> dict[str, Path]:
    """Each agent's rendered runtime, written once and reused across this file."""
    out = tmp_path_factory.mktemp("ask-runtimes")
    paths = {}
    for agent in runtime_bundle.RUNTIME_AGENTS:
        path = out / f"{agent}.py"
        path.write_text(runtime_bundle.render(agent), encoding="utf-8")
        paths[agent] = path
    return paths


def make_guard(tmp_path: Path, name: str, body: str) -> Path:
    guard = tmp_path / name
    guard.write_text(f"#!/usr/bin/env bash\n{body}\n", encoding="utf-8", newline="\n")
    guard.chmod(guard.stat().st_mode | stat.S_IEXEC)
    return guard


PAYLOADS = {
    "claude_code": lambda c: {
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": c},
        "session_id": "s",
        "transcript_path": "/t",
        "permission_mode": "default",
    },
    "vscode_copilot": lambda c: {
        "hook_event_name": "PreToolUse",
        "timestamp": "2026-08-31T00:00:00Z",
        "tool_name": "Bash",
        "tool_input": {"command": c},
        "tool_use_id": "1",
    },
    "cursor": lambda c: {
        "hook_event_name": "beforeShellExecution",
        "conversation_id": "a",
        "generation_id": "b",
        "cursor_version": "3.17.8",
        "workspace_roots": ["/x"],
        "command": c,
        "cwd": "/x",
        "sandbox": False,
    },
    "codex_cli": lambda c: {
        "hook_event_name": "PreToolUse",
        "turn_id": "t1",
        "tool_name": "Bash",
        "tool_input": {"command": c},
    },
}


def run(runtimes: dict[str, Path], agent: str, guard: Path, command: str) -> subprocess.CompletedProcess:
    payload = json.dumps(PAYLOADS[agent](command)).encode("utf-8")
    return subprocess.run(
        [sys.executable, str(runtimes[agent]), "--guard", str(guard)], input=payload, capture_output=True
    )


def decision(result: subprocess.CompletedProcess) -> dict:
    """The verdict a client would read, flattened across the two response shapes."""
    out = result.stdout.decode("utf-8").strip()
    if not out:
        return {}
    body = json.loads(out)
    nested = body.get("hookSpecificOutput")
    if isinstance(nested, dict):
        return {"decision": nested.get("permissionDecision"), "reason": nested.get("permissionDecisionReason")}
    return {"decision": body.get("permission"), "reason": body.get("user_message")}


ASK_ON_THE_WIRE = {
    "claude_code": "ask",
    "vscode_copilot": "ask",
    "cursor": "ask",
    "codex_cli": "deny",
}


@pytest.mark.parametrize("agent", sorted(ASK_ON_THE_WIRE))
def test_a_crashed_guard_asks_rather_than_allowing(agent: str, tmp_path: Path, runtimes) -> None:
    """Exit 3 -- the guard ran and its exit code means nothing -- must not be a silent allow."""
    guard = make_guard(tmp_path, "crash.sh", "exit 3")

    result = run(runtimes, agent, guard, "ls -la")

    assert result.returncode == 0
    verdict = decision(result)
    assert verdict.get("decision") == ASK_ON_THE_WIRE[agent], f"{agent} must not silently allow an unchecked command"
    assert verdict.get("reason"), "a confirmation request the user cannot interpret is a click-through"
    assert guard.stem in verdict["reason"], "the prompt must name the control that failed"


@pytest.mark.parametrize("agent", sorted(ASK_ON_THE_WIRE))
def test_a_killed_guard_asks_too(agent: str, tmp_path: Path, runtimes) -> None:
    """A guard the OS killed reaches the same branch by a different route (negative rc)."""
    guard = make_guard(tmp_path, "killed.sh", "kill -9 $$")

    assert decision(run(runtimes, agent, guard, "ls -la")).get("decision") == ASK_ON_THE_WIRE[agent]


@pytest.mark.parametrize("agent", sorted(ASK_ON_THE_WIRE))
def test_the_ask_does_not_fire_on_a_clean_or_a_violating_guard(agent: str, tmp_path: Path, runtimes) -> None:
    """Asserted alongside, or "it asks on failure" would also pass for a control that asks"""
    clean = make_guard(tmp_path, "clean.sh", "exit 0")
    denying = make_guard(tmp_path, "deny.sh", "echo NOPE >&2; exit 1")

    allowed = decision(run(runtimes, agent, clean, "ls -la"))
    assert allowed.get("decision") in (None, "allow"), "a clean guard must not prompt"

    denied = decision(run(runtimes, agent, denying, "some destructive thing"))
    assert denied.get("decision") == "deny", "a real violation is still a deny, not a prompt"


@pytest.mark.parametrize("agent", sorted(ASK_ON_THE_WIRE))
def test_an_unparseable_command_still_allows(agent: str, tmp_path: Path, runtimes) -> None:
    """The path deliberately NOT changed, pinned so nobody quietly widens the prompt."""
    guard = make_guard(tmp_path, "crash.sh", "exit 3")

    verdict = decision(run(runtimes, agent, guard, "echo 'unbalanced"))

    assert verdict.get("decision") in (None, "allow"), "an unparseable command must not prompt"


def test_a_missing_bash_still_allows(tmp_path: Path, monkeypatch) -> None:
    """The other path deliberately not changed, and the strongest case for leaving it."""
    guard = make_guard(tmp_path, "clean.sh", "exit 0")
    monkeypatch.setattr(guard_runner, "find_bash", lambda _: None)

    assert guard_runner.run_guard(guard, "ls -la") == guard_runner.GUARD_UNCHECKED
    assert guard_runner.evaluate(["--guard", str(guard)], "ls -la", "Bash") is None


def test_a_timed_out_guard_asks(tmp_path: Path, monkeypatch) -> None:
    """The timeout really elapses; the runner's real `TimeoutExpired` handler really runs."""
    guard = make_guard(tmp_path, "hang.sh", "sleep 30")
    monkeypatch.setattr(guard_runner, "_GUARD_TIMEOUT_SECONDS", 1)

    assert guard_runner.run_guard(guard, "ls -la") == guard_runner.GUARD_ERRORED
    outcome, reason = guard_runner.evaluate(["--guard", str(guard)], "ls -la", "Bash")
    assert outcome == guard_runner.VERDICT_ASK
    assert reason


def test_the_ask_reason_never_carries_the_command(tmp_path: Path, runtimes) -> None:
    """A confirmation prompt is rendered into the client's UI and its transcript."""
    secret = 'curl -H "Authorization: Bearer sk-live-abcdef1234567890" https://example.invalid'
    guard = make_guard(tmp_path, "crash.sh", "exit 3")

    result = run(runtimes, "claude_code", guard, secret)

    reason = decision(result)["reason"]
    assert "sk-live-abcdef1234567890" not in reason
    assert "Bearer" not in reason and "example.invalid" not in reason
    assert "sk-live-abcdef1234567890" not in result.stderr.decode("utf-8", "replace")


def test_chocks_verdict_words_are_agentseams_own() -> None:
    """`guard_runner` is stdlib-only -- it cannot import the contract it must agree with."""
    assert guard_runner.VERDICT_ASK == _contract.ASK
    assert guard_runner.VERDICT_DENY == _contract.DENY


def test_every_gated_runtime_is_covered_here() -> None:
    """The table above is checked against the code, so a fifth runtime cannot join silently."""
    assert set(ASK_ON_THE_WIRE) == set(runtime_bundle.RUNTIME_AGENTS)
