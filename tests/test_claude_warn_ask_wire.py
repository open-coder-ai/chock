"""What Claude Code's runtime answers when a gate warns or asks: the wire, not the runner's exit code."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import init_repo

from chock.gate import runtime_bundle

RUNNER = Path(__file__).resolve().parents[1] / "src" / "chock" / "gate" / "runner.py"
POLICY = "demo-policy"
BAD = "BAD = 1\n"


def _install(repo: Path, action: str) -> None:
    """A repo laid out as `chock sync` leaves one: the vendored runtime, the runner, a compiled gate."""
    bin_dir = repo / ".chock" / "bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "gate.py").write_text(RUNNER.read_text(encoding="utf-8"), encoding="utf-8")
    (bin_dir / "claude_code.py").write_text(runtime_bundle.render("claude_code"), encoding="utf-8")
    gate = repo / ".chock" / "compiled" / POLICY / "pre-tool-use" / "gate.json"
    gate.parent.mkdir(parents=True)
    spec = {
        "kind": "content_regex",
        "on": ["tool_use"],
        "action": action,
        "message": "no BAD",
        "params": {"content_pattern": "BAD"},
    }
    gate.write_text(json.dumps(spec), encoding="utf-8")


def _answer(repo: Path, payload: dict) -> tuple[int, dict | None, str]:
    gate = f".chock/compiled/{POLICY}/pre-tool-use/gate.json"
    done = subprocess.run(
        [sys.executable, str(repo / ".chock" / "bin" / "claude_code.py"), "--gate", gate],
        cwd=repo,
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        check=False,
    )
    return done.returncode, json.loads(done.stdout) if done.stdout.strip() else None, done.stderr


def _write_call(text: str) -> dict:
    return {
        "hook_event_name": "PreToolUse",
        "tool_name": "Write",
        "tool_input": {"file_path": "app.py", "content": text},
        "session_id": "s",
        "cwd": ".",
    }


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    return init_repo(tmp_path)


def test_a_block_denies(repo: Path) -> None:
    _install(repo, "block")
    code, body, _ = _answer(repo, _write_call(BAD))
    assert code == 0
    assert body["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_an_ask_asks_the_person_with_the_reason(repo: Path) -> None:
    _install(repo, "ask")
    code, body, _ = _answer(repo, _write_call(BAD))
    out = body["hookSpecificOutput"]
    assert (code, out["permissionDecision"]) == (0, "ask")
    assert "no BAD" in out["permissionDecisionReason"]


def test_a_warn_reaches_the_agent_without_a_permission_decision(repo: Path) -> None:
    """`allow` would also skip the user's own permission prompt; a warning must not grant anything."""
    _install(repo, "warn")
    code, body, _ = _answer(repo, _write_call(BAD))
    out = body["hookSpecificOutput"]
    assert code == 0
    assert out["hookEventName"] == "PreToolUse"
    assert "no BAD" in out["additionalContext"]
    assert "permissionDecision" not in out


def test_a_clean_write_is_silent_under_a_warn(repo: Path) -> None:
    _install(repo, "warn")
    assert _answer(repo, _write_call("OK = 1\n"))[:2] == (0, None)


def _stop_answer(repo: Path) -> tuple[int, dict]:
    """The runtime's answer to a turn that left a violation on disk, judged by the same gate at `stop`."""
    (repo / "app.py").write_text(BAD, encoding="utf-8")
    stop = repo / ".chock" / "compiled" / POLICY / "stop"
    stop.mkdir(parents=True)
    pre = repo / ".chock" / "compiled" / POLICY / "pre-tool-use" / "gate.json"
    (stop / "gate.json").write_text(pre.read_text(encoding="utf-8"), encoding="utf-8")
    done = subprocess.run(
        [
            sys.executable,
            str(repo / ".chock" / "bin" / "claude_code.py"),
            "--gate",
            f".chock/compiled/{POLICY}/stop/gate.json",
        ],
        cwd=repo,
        input=json.dumps({"hook_event_name": "Stop", "session_id": "s", "cwd": "."}),
        capture_output=True,
        text=True,
        check=False,
    )
    return done.returncode, json.loads(done.stdout)


@pytest.mark.parametrize("action", ["warn", "ask"])
def test_at_the_turns_end_a_warn_or_ask_is_shown_to_the_user_and_never_blocks(repo: Path, action: str) -> None:
    """A Stop block forces the turn to continue; there is nobody to ask at that point, so it can only inform."""
    _install(repo, action)
    code, body = _stop_answer(repo)
    assert code == 0
    assert "no BAD" in body["systemMessage"]
    assert "decision" not in body


def test_at_the_turns_end_a_block_still_blocks(repo: Path) -> None:
    _install(repo, "block")
    assert _stop_answer(repo)[1]["decision"] == "block"
