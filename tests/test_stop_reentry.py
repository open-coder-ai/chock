"""A client that re-enters the Stop hook in one turn is judged again, never waved through and never looped.

Claude Code, Codex and Copilot send `stop_hook_active`; Cursor sends `loop_count`. Neither says how
often, so the gate keeps its own count in the session log and caps what it will refuse.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from conftest import init_repo

from chock.gate import stop_reentry, write_gate

SECRET = "AKIA" + "1234567890ABCDEF"  # pragma: allowlist secret
SPEC = {
    "kind": "content_regex",
    "on": ["commit", "tool_use"],
    "action": "block",
    "message": "secret-shaped string",
    "params": {"scan": "added_lines", "content_pattern": r"AKIA[0-9A-Z]{16}"},
}

#: How each client marks the i-th Stop of a turn (0 is the first).
SIGNALS = {
    "stop_hook_active": lambda i: {"stop_hook_active": bool(i)},
    "loop_count": lambda i: {"loop_count": i},
}


@pytest.fixture(params=sorted(SIGNALS))
def signal(request: pytest.FixtureRequest):
    return SIGNALS[request.param]


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    init_repo(tmp_path)
    gate = tmp_path / ".chock" / "compiled" / "leaky" / "stop" / "gate.json"
    gate.parent.mkdir(parents=True)
    gate.write_text(json.dumps(SPEC), encoding="utf-8")
    runner = tmp_path / ".chock" / "bin" / "gate.py"
    runner.parent.mkdir(parents=True)
    runner.write_text((Path(write_gate.__file__).parent / "runner.py").read_text(encoding="utf-8"), encoding="utf-8")
    return tmp_path


def _leak(repo: Path, name: str) -> None:
    (repo / name).write_text(f'key = "{SECRET}"\n', encoding="utf-8")


def _stop(repo: Path, raw: dict):
    gate = repo / ".chock" / "compiled" / "leaky" / "stop" / "gate.json"
    return write_gate.evaluate_gate(["--gate", str(gate)], SimpleNamespace(event="stop", raw=raw, cwd=str(repo)))


def _denied(decision) -> bool:
    return decision is not None and decision[0] == write_gate.VERDICT_DENY


def test_the_first_stop_of_a_turn_refuses(repo: Path, signal) -> None:
    _leak(repo, "a.py")
    decision = _stop(repo, signal(0))
    assert _denied(decision) and "a.py" in decision[1]


def test_a_re_entry_with_the_findings_already_told_is_allowed_and_ends_the_turn(repo: Path, signal) -> None:
    _leak(repo, "a.py")
    assert _denied(_stop(repo, signal(0)))
    assert _stop(repo, signal(1)) is None
    assert _stop(repo, signal(2)) is None, "an identical set stays allowed, so the client cannot loop"


def test_a_re_entry_with_a_new_violation_is_refused(repo: Path, signal) -> None:
    _leak(repo, "a.py")
    assert _denied(_stop(repo, signal(0)))
    _leak(repo, "b.py")
    decision = _stop(repo, signal(1))
    assert _denied(decision) and "b.py" in decision[1]


def test_a_re_entry_where_the_violation_changed_is_refused(repo: Path, signal) -> None:
    _leak(repo, "a.py")
    assert _denied(_stop(repo, signal(0)))
    (repo / "a.py").unlink()
    _leak(repo, "moved.py")
    decision = _stop(repo, signal(1))
    assert _denied(decision) and "moved.py" in decision[1]


def test_the_nth_re_entry_refuses_for_a_person_and_the_next_one_lets_the_turn_end(repo: Path, signal) -> None:
    assert _stop(repo, signal(0)) is None
    for i in range(stop_reentry.REENTRY_CAP + 1):
        _leak(repo, f"leak{i}.py")
        decision = _stop(repo, signal(i))
        assert _denied(decision), f"stop {i} carries findings the turn was not yet told"
    assert "a person must review" in decision[1]
    _leak(repo, "late.py")
    assert _stop(repo, signal(stop_reentry.REENTRY_CAP + 1)) is None, "past the cap the turn must be able to end"


def test_an_earlier_re_entry_does_not_ask_for_a_person(repo: Path, signal) -> None:
    _leak(repo, "a.py")
    assert _denied(_stop(repo, signal(0)))
    _leak(repo, "b.py")
    assert "a person must review" not in _stop(repo, signal(1))[1]


def test_a_clean_turn_is_allowed_at_the_first_stop_and_on_re_entry(repo: Path, signal) -> None:
    (repo / "fine.py").write_text("x = 1\n", encoding="utf-8")
    assert _stop(repo, signal(0)) is None
    assert _stop(repo, signal(1)) is None


def test_a_violation_fixed_after_the_refusal_is_allowed(repo: Path, signal) -> None:
    _leak(repo, "a.py")
    assert _denied(_stop(repo, signal(0)))
    (repo / "a.py").unlink()
    assert _stop(repo, signal(1)) is None


def test_the_next_turn_is_told_again(repo: Path, signal) -> None:
    _leak(repo, "a.py")
    assert _denied(_stop(repo, signal(0)))
    assert _stop(repo, signal(1)) is None
    assert _denied(_stop(repo, signal(0))), "a first stop is never waved through"


def test_a_ledger_that_cannot_be_written_allows_rather_than_loops(repo: Path, signal) -> None:
    (repo / ".chock" / "state").write_text("not a directory", encoding="utf-8")
    _leak(repo, "a.py")
    assert _denied(_stop(repo, signal(0)))
    assert _stop(repo, signal(1)) is None


def test_the_session_log_keeps_digests_and_never_file_contents(repo: Path, signal) -> None:
    _leak(repo, "a.py")
    _stop(repo, signal(0))
    _stop(repo, signal(1))
    text = "".join(p.read_text(encoding="utf-8") for p in (repo / ".chock" / "state").glob("*.jsonl"))
    assert '"phase": "stop"' in text and SECRET not in text and "a.py" not in text


def test_every_re_entry_verdict_reaches_the_gate_log(repo: Path, signal, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CHOCK_GATE_LOG")
    _leak(repo, "a.py")
    _stop(repo, signal(0))
    _stop(repo, signal(1))
    _leak(repo, "b.py")
    _stop(repo, signal(2))
    (repo / "a.py").unlink()
    (repo / "b.py").unlink()
    _stop(repo, signal(3))
    lines = (repo / ".chock" / "log" / "gate-events.jsonl").read_text(encoding="utf-8").splitlines()
    records = [r for r in map(json.loads, lines) if r.get("kind") == "reentry"]
    assert [(r["reentry"], r["verdict"], r["policy_id"], r["surface"]) for r in records] == [
        (1, "already-reported", "leaky", "stop-reentry"),
        (2, "refused", "leaky", "stop-reentry"),
        (3, "clean", "leaky", "stop-reentry"),
    ]


def test_a_first_stop_writes_no_re_entry_record(repo: Path, signal, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CHOCK_GATE_LOG")
    _leak(repo, "a.py")
    _stop(repo, signal(0))
    log = repo / ".chock" / "log" / "gate-events.jsonl"
    assert not log.exists() or '"reentry"' not in log.read_text(encoding="utf-8")


def test_a_count_the_client_sends_is_trusted_over_a_shorter_ledger(repo: Path) -> None:
    """Cursor says how often it re-entered: a cleared ledger cannot reset the cap."""
    _leak(repo, "a.py")
    assert _stop(repo, {"loop_count": stop_reentry.REENTRY_CAP + 1}) is None
