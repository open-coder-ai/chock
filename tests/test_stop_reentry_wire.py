"""Stop re-entry end to end through each vendor's installed runtime, in the payload shape that vendor sends.

Claude Code, Codex and Copilot mark a re-entry with `stop_hook_active`; Cursor counts with `loop_count`
and answers a refusal with `followup_message`. Every one refuses until the cap and then ends the turn
with a warning the user sees: `systemMessage` where the vendor documents one, stderr where it does not.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from test_stop_install import POLICY_ID, SECRET, _repo

from chock.gate.stop_reentry import REENTRY_CAP
from chock.hooks.in_agent_install import install_hooks

STAMP = "2026-09-28T09:00:00.000Z"


def _claude(repo: Path, i: int) -> dict:
    return {"hook_event_name": "Stop", "session_id": "s1", "cwd": str(repo), "stop_hook_active": bool(i)}


def _codex(repo: Path, i: int) -> dict:
    return {
        "hook_event_name": "Stop",
        "session_id": "s1",
        "turn_id": "t1",
        "cwd": str(repo),
        "transcript_path": None,
        "model": "gpt-5",
        "stop_hook_active": bool(i),
    }


def _copilot(repo: Path, i: int) -> dict:
    return {
        "hook_event_name": "Stop",
        "session_id": "s1",
        "timestamp": STAMP,
        "cwd": str(repo),
        "transcript_path": str(repo / "t.jsonl"),
        "stop_reason": "end_turn",
        "stop_hook_active": bool(i),
    }


def _cursor(repo: Path, i: int) -> dict:
    envelope = {"conversation_id": "c", "generation_id": "g", "cursor_version": "3.21.18"}
    return {
        **envelope,
        "hook_event_name": "stop",
        "workspace_roots": [str(repo)],
        "status": "completed",
        "loop_count": i,
    }


def _refusal_text(body: dict) -> str | None:
    return body.get("reason") or body.get("followup_message")


#: vendor -> (payload for the i-th stop, whether the cap warning is a `systemMessage`)
VENDORS = {
    "claude_code": (_claude, True),
    "codex_cli": (_codex, True),
    "vscode_copilot": (_copilot, True),
    "cursor": (_cursor, False),
}


def _fire(repo: Path, agent: str, payload: dict) -> subprocess.CompletedProcess:
    gate = repo / ".chock" / "compiled" / POLICY_ID / "stop" / "gate.json"
    proc = subprocess.run(
        [sys.executable, str(repo / ".chock" / "bin" / f"{agent}.py"), "--gate", str(gate)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=str(repo),
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    return proc


@pytest.fixture(params=sorted(VENDORS))
def vendor(request: pytest.FixtureRequest, tmp_path: Path):
    repo = _repo(tmp_path)
    install_hooks(repo, request.param)
    return request.param, repo


def test_every_re_entry_up_to_the_cap_is_refused_in_the_vendor_s_own_words(vendor) -> None:
    agent, repo = vendor
    payload, _ = VENDORS[agent]
    (repo / "leak.py").write_text(f'aws = "{SECRET}"\n', encoding="utf-8")
    for i in range(REENTRY_CAP + 1):
        body = json.loads(_fire(repo, agent, payload(repo, i)).stdout)
        text = _refusal_text(body) or _refusal_text(body.get("hookSpecificOutput", {}))
        assert text and "leak.py" in text, (agent, i, body)
    assert "still on disk" in text and "commit will refuse" in text, "the last refusal says what comes next"


def test_past_the_cap_the_turn_ends_with_a_warning_the_user_sees(vendor) -> None:
    agent, repo = vendor
    payload, speaks = VENDORS[agent]
    (repo / "leak.py").write_text(f'aws = "{SECRET}"\n', encoding="utf-8")
    for i in range(REENTRY_CAP + 1):
        _fire(repo, agent, payload(repo, i))
    proc = _fire(repo, agent, payload(repo, REENTRY_CAP + 1))
    if speaks:
        body = json.loads(proc.stdout)
        assert set(body) == {"systemMessage"}, "a warning, never a block that would loop"
        assert "still on disk" in body["systemMessage"] and "leak.py" in body["systemMessage"]
    else:
        assert proc.stdout.strip() == "", "no follow-up: the turn ends"
    assert "still on disk" in proc.stderr and "commit will refuse" in proc.stderr
    log = (repo / ".chock" / "log" / "gate-events.jsonl").read_text(encoding="utf-8").splitlines()
    (held,) = [r for r in map(json.loads, log) if r.get("kind") == "reentry"]
    assert (held["verdict"], held["would_block"], held["reentry"]) == ("warn", True, REENTRY_CAP + 1)


def test_a_clean_re_entry_is_silent(vendor) -> None:
    agent, repo = vendor
    payload, _ = VENDORS[agent]
    (repo / "leak.py").write_text(f'aws = "{SECRET}"\n', encoding="utf-8")
    _fire(repo, agent, payload(repo, 0))
    (repo / "leak.py").unlink()
    proc = _fire(repo, agent, payload(repo, 1))
    assert proc.stdout.strip() == "" and "still on disk" not in proc.stderr


def test_codex_keys_the_turn_on_its_turn_id(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    install_hooks(repo, "codex_cli")
    (repo / "leak.py").write_text(f'aws = "{SECRET}"\n', encoding="utf-8")
    _fire(repo, "codex_cli", _codex(repo, 0))
    records = (repo / ".chock" / "state" / "s1.stop.jsonl").read_text(encoding="utf-8").splitlines()
    assert [json.loads(r)["turn"] for r in records] == ["t1"]


def test_cursor_s_count_comes_from_its_payload(tmp_path: Path) -> None:
    """`loop_count` is Cursor's own: a ledger the agent deleted does not restart it."""
    repo = _repo(tmp_path)
    install_hooks(repo, "cursor")
    (repo / "leak.py").write_text(f'aws = "{SECRET}"\n', encoding="utf-8")
    assert "followup_message" in json.loads(_fire(repo, "cursor", _cursor(repo, 0)).stdout)
    (repo / ".chock" / "state" / "c.stop.jsonl").unlink()
    assert _fire(repo, "cursor", _cursor(repo, REENTRY_CAP + 1)).stdout.strip() == ""
