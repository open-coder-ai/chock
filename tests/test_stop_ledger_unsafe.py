"""A stop ledger that is not a plain file in real directories is never opened: the Stop is refused, and nothing hangs.

A FIFO would block the hook until the client's timeout, which a client may read as an allow; a symlink would make
chock append to its target. Both ledgers (`<session>.stop.jsonl` and `unreadable-stop.jsonl`) and the gate log.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pytest
from test_stop_install import POLICY_ID, SECRET, _repo

from chock.gate import runtime_bundle
from chock.gate.stop_reentry import REENTRY_CAP
from chock.hooks.in_agent_install import install_hooks

TIMEOUT_SECONDS = 20
OUTSIDE = "outside"


def _fifo(path: Path, outside: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    os.mkfifo(path)


def _symlinked_file(path: Path, outside: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    (outside / "target.jsonl").write_text("", encoding="utf-8")
    path.symlink_to(outside / "target.jsonl")


def _symlinked_state(path: Path, outside: Path) -> None:
    path.parent.parent.mkdir(parents=True, exist_ok=True)
    path.parent.symlink_to(outside, target_is_directory=True)


def _directory(path: Path, outside: Path) -> None:
    path.mkdir(parents=True)


UNSAFE = {
    "fifo": _fifo,
    "symlinked-file": _symlinked_file,
    "symlinked-state": _symlinked_state,
    "directory": _directory,
}
Plant = Callable[[Path, Path], None]


def _run(argv: list[str], cwd: Path, payload: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        argv, cwd=cwd, input=payload, capture_output=True, text=True, timeout=TIMEOUT_SECONDS, check=False
    )


def _untouched(outside: Path) -> bool:
    return all(not p.read_text(encoding="utf-8") for p in outside.iterdir() if p.is_file())


@pytest.fixture
def outside(tmp_path: Path) -> Path:
    path = tmp_path / OUTSIDE
    path.mkdir()
    return path


# --- #208's per-session ledger, through the installed Claude Code runtime -----------------------


def _session_stop(repo: Path, reentry: bool) -> subprocess.CompletedProcess:
    gate = repo / ".chock" / "compiled" / POLICY_ID / "stop" / "gate.json"
    payload = {"hook_event_name": "Stop", "session_id": "s1", "cwd": str(repo), "stop_hook_active": reentry}
    argv = [sys.executable, str(repo / ".chock" / "bin" / "claude_code.py"), "--gate", str(gate)]
    return _run(argv, repo, json.dumps(payload))


@pytest.mark.parametrize("plant", UNSAFE.values(), ids=UNSAFE)
def test_an_unsafe_session_ledger_is_never_opened_and_the_turn_never_ends_silently(
    tmp_path: Path, outside: Path, plant: Plant
) -> None:
    """The first stop is refused; a re-entry has nothing to count, so it ends loudly (the pinned #208 behaviour)."""
    repo = _repo(tmp_path)
    install_hooks(repo, "claude_code")
    (repo / "leak.py").write_text(f'aws = "{SECRET}"\n', encoding="utf-8")
    plant(repo / ".chock" / "state" / "s1.stop.jsonl", outside)
    first = _session_stop(repo, False)
    assert json.loads(first.stdout).get("decision") == "block", (first.stdout, first.stderr)
    again = _session_stop(repo, True)
    assert set(json.loads(again.stdout)) == {"systemMessage"} and "still on disk" in again.stderr, again.stdout
    assert _untouched(outside)


def test_a_regular_session_ledger_still_counts_and_caps(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    install_hooks(repo, "claude_code")
    (repo / "leak.py").write_text(f'aws = "{SECRET}"\n', encoding="utf-8")
    for turn in range(REENTRY_CAP + 1):
        assert json.loads(_session_stop(repo, bool(turn)).stdout).get("decision") == "block", turn
    capped = _session_stop(repo, True)
    assert set(json.loads(capped.stdout)) == {"systemMessage"} and "still on disk" in capped.stderr


# --- the unreadable-payload ledger and the gate log ---------------------------------------------


@pytest.fixture
def unreadable(tmp_path: Path) -> Callable[[], subprocess.CompletedProcess]:
    runtime = tmp_path / "claude_code.py"
    runtime.write_text(runtime_bundle.render("claude_code"), encoding="utf-8")
    gate = tmp_path / "stop" / "gate.json"
    gate.parent.mkdir()
    gate.write_text(json.dumps({"kind": "script", "on": ["tool_call"], "action": "block", "params": {}}), "utf-8")
    return lambda: _run([sys.executable, str(runtime), "--gate", str(gate)], tmp_path, "")


def _blocked(done: subprocess.CompletedProcess) -> bool:
    return json.loads(done.stdout or "{}").get("decision") == "block"


@pytest.mark.parametrize("plant", UNSAFE.values(), ids=UNSAFE)
def test_an_unsafe_unreadable_stop_ledger_refuses_every_stop_and_is_never_written(
    tmp_path: Path, outside: Path, unreadable: Callable, plant: Plant
) -> None:
    plant(tmp_path / ".chock" / "state" / "unreadable-stop.jsonl", outside)
    for turn in range(REENTRY_CAP + 2):
        done = unreadable()
        assert _blocked(done), (turn, done.stdout, done.stderr)
    assert _untouched(outside)


@pytest.mark.parametrize("plant", [_fifo, _symlinked_file], ids=["fifo", "symlinked-file"])
def test_an_unsafe_gate_log_neither_hangs_nor_loosens_the_refusal(
    tmp_path: Path, outside: Path, unreadable: Callable, plant: Plant
) -> None:
    plant(tmp_path / ".chock" / "log" / "gate-events.jsonl", outside)
    for turn in range(REENTRY_CAP + 1):
        done = unreadable()
        assert (turn < REENTRY_CAP) == _blocked(done), (turn, done.stdout)
    assert _untouched(outside)


def test_a_regular_unreadable_stop_ledger_still_counts_and_caps(tmp_path: Path, unreadable: Callable) -> None:
    for turn in range(REENTRY_CAP):
        assert _blocked(unreadable()), turn
    assert not _blocked(unreadable())
