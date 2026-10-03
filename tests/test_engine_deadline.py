"""One hook invocation spends ONE engine budget across every subprocess, so the engine's timers fire before the client's."""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from chock.gate import budget, guard_runner, write_gate

ENGINE_BUDGET = budget.ENGINE_BUDGET_SECONDS


class _Clock:
    """A fake monotonic clock: a stubbed subprocess spends it instead of sleeping."""

    def __init__(self) -> None:
        self.now = 1000.0

    def monotonic(self) -> float:
        return self.now


def _slow(clock: _Clock, takes, spawned: list[Any]):
    """A `subprocess.run` that takes `takes(argv)` seconds, or is cut off at its timeout like the real one."""

    def run(argv, **kwargs):
        spawned.append((argv, kwargs["timeout"]))
        need = takes(argv)
        if need > kwargs["timeout"]:
            clock.now += kwargs["timeout"]
            raise subprocess.TimeoutExpired(argv, kwargs["timeout"])
        clock.now += need
        return subprocess.CompletedProcess(argv, 0, stdout="?? app.py\0" if argv[1] == "-C" else "", stderr="")

    return run


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> _Clock:
    fake = _Clock()
    monkeypatch.setattr(budget, "time", SimpleNamespace(monotonic=fake.monotonic))
    return fake


def _stop_gate(tmp_path: Path) -> Path:
    gate = tmp_path / ".chock" / "compiled" / "scan" / "stop" / "gate.json"
    gate.parent.mkdir(parents=True)
    gate.write_text("{}", encoding="utf-8")
    runner = tmp_path / ".chock" / "bin" / "gate.py"
    runner.parent.mkdir(parents=True)
    runner.write_text("", encoding="utf-8")
    (tmp_path / "app.py").write_text("x = 1\n", encoding="utf-8")
    return gate


def _stop_event():
    return SimpleNamespace(event="stop", path=None, content=None, raw={})


def test_a_stuck_git_status_at_stop_refuses_within_the_budget(tmp_path, monkeypatch, clock, capsys) -> None:
    gate = _stop_gate(tmp_path)
    spawned: list[Any] = []
    monkeypatch.setattr(subprocess, "run", _slow(clock, lambda argv: 3600 if "status" in argv else 0, spawned))

    decision = write_gate.evaluate_gate(["--gate", str(gate)], _stop_event())

    assert decision is not None and decision[0] == write_gate.VERDICT_DENY, "a worktree never listed is not a clean one"
    assert "could not check" in decision[1]
    assert "git status" in capsys.readouterr().err
    assert clock.now - 1000.0 <= ENGINE_BUDGET
    assert len(spawned) == 1, "no gate run follows a listing that never finished"


def test_git_status_and_the_gate_share_one_budget_at_stop(tmp_path, monkeypatch, clock) -> None:
    gate = _stop_gate(tmp_path)
    spawned: list[Any] = []

    def takes(argv):
        return 20 if "status" in argv else 3600

    monkeypatch.setattr(subprocess, "run", _slow(clock, takes, spawned))

    decision = write_gate.evaluate_gate(["--gate", str(gate)], _stop_event())

    assert decision is not None and decision[0] == write_gate.VERDICT_DENY
    assert clock.now - 1000.0 <= ENGINE_BUDGET, "30 s of status plus 30 s of gate was 60 s against a 45 s client"
    status, runner = spawned
    assert status[1] == pytest.approx(ENGINE_BUDGET)
    assert runner[1] == pytest.approx(ENGINE_BUDGET - 20)


def test_changed_paths_says_none_when_git_times_out(tmp_path, monkeypatch, clock) -> None:
    monkeypatch.setattr(subprocess, "run", _slow(clock, lambda argv: 3600, []))
    assert write_gate.changed_paths(tmp_path) is None
    assert write_gate.writes_from_worktree(tmp_path) is None


def test_bash_probes_are_spent_from_the_deadline(tmp_path, monkeypatch, clock) -> None:
    spawned: list[Any] = []
    monkeypatch.setattr(guard_runner, "_FOUND_BASH", {})
    monkeypatch.setattr(guard_runner, "bash_candidates", lambda: ["a", "b", "c"])
    monkeypatch.setattr(subprocess, "run", _slow(clock, lambda argv: 3600, spawned))

    assert guard_runner.find_bash(tmp_path / "g.sh", clock.now + 12) is None

    assert [timeout for _, timeout in spawned] == [10, 2], "the third probe never starts: the budget is spent"
    assert clock.now - 1000.0 == 12


def test_a_guard_whose_shell_probes_eat_the_budget_asks_within_it(tmp_path, monkeypatch, clock, capsys) -> None:
    guard = tmp_path / "g.sh"
    guard.write_text("exit 0\n", encoding="utf-8")
    monkeypatch.setattr(guard_runner, "_FOUND_BASH", {})
    monkeypatch.setattr(guard_runner, "bash_candidates", lambda: ["a", "b", "c", "d"])
    monkeypatch.setattr(subprocess, "run", _slow(clock, lambda argv: 3600, []))

    assert guard_runner.run_guard(guard, "ls") == guard_runner.GUARD_ERRORED
    assert clock.now - 1000.0 <= ENGINE_BUDGET
    assert "timed out" in capsys.readouterr().err


def test_a_guard_run_gets_only_what_the_probe_left(tmp_path, monkeypatch, clock) -> None:
    guard = tmp_path / "g.sh"
    guard.write_text("exit 0\n", encoding="utf-8")
    spawned: list[Any] = []
    monkeypatch.setattr(guard_runner, "_FOUND_BASH", {})
    monkeypatch.setattr(guard_runner, "bash_candidates", lambda: ["a"])
    monkeypatch.setattr(subprocess, "run", _slow(clock, lambda argv: 8 if argv[1] == "-c" else 3600, spawned))

    assert guard_runner.run_guard(guard, "ls") == guard_runner.GUARD_ERRORED
    assert [timeout for _, timeout in spawned] == [10, pytest.approx(ENGINE_BUDGET - 8)]
    assert clock.now - 1000.0 <= ENGINE_BUDGET
