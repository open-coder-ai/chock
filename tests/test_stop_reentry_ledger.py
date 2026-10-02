"""The Stop ledger cannot be edited into a silent end: tampering refuses or warns, never allows quietly.

Split from test_stop_reentry.py, which asks what an intact ledger decides.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from test_stop_reentry import CAP, SIGNALS, _denied, _leak, _reentry_log, _stop, _warned, make_repo

from chock.gate import stop_reentry


def _ledger(repo: Path) -> Path:
    return repo / ".chock" / "state" / "s1.stop.jsonl"


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    return make_repo(tmp_path)


@pytest.fixture(params=sorted(SIGNALS))
def signal(request: pytest.FixtureRequest):
    return SIGNALS[request.param]


def _fake(**fields) -> str:
    base = {"ts": "2026-01-01T00:00:00Z", "session_id": "s1", "phase": "stop", "policy": "leaky", "turn": None}
    return json.dumps({**base, **fields}) + "\n"


TAMPERS = {
    "malformed padding": lambda p: p.open("a").write(
        json.dumps({"phase": "stop", "policy": "leaky", "reentry": 9}) + "\n"
    ),
    "garbage": lambda p: p.write_text("garbage\n", encoding="utf-8"),
    "nested past the recursion limit": lambda p: p.write_text("[" * 200_000 + "\n", encoding="utf-8"),
    "deleted": lambda p: p.unlink(),
    "a fresh first stop": lambda p: p.open("a").write(_fake(reentry=0, verdict="allow", findings=[])),
    "a count past the cap": lambda p: p.open("a").write(_fake(reentry=CAP + 5, verdict="block", findings=[])),
    "a gap in the count": lambda p: p.open("a").write(_fake(reentry=CAP, verdict="block", findings=[])),
    "a directory": lambda p: (p.unlink(), p.mkdir()),
}


@pytest.mark.parametrize("tamper", sorted(TAMPERS))
def test_no_tampering_ends_a_turn_with_findings_silently(repo: Path, signal, tamper: str) -> None:
    _leak(repo, "a.py")
    assert _denied(_stop(repo, signal(0)))
    TAMPERS[tamper](_ledger(repo))
    _leak(repo, "b.py")
    for i in range(1, CAP + 3):
        decision = _stop(repo, signal(i))
        assert _denied(decision) or _warned(decision), f"re-entry {i} after {tamper!r} allowed silently"
        if _warned(decision):
            assert "still on disk" in decision[1]


def test_a_forged_count_can_only_bring_the_warning_forward(repo: Path) -> None:
    """A client with no count of its own reads the ledger's; a forged one ends the turn loudly, not quietly."""
    _leak(repo, "a.py")
    _stop(repo, {"session_id": "s1"})
    _ledger(repo).open("a").write(_fake(reentry=CAP, verdict="block", findings=[], anchor=True))
    assert _warned(_stop(repo, {"session_id": "s1", "stop_hook_active": True}))


def test_a_client_that_counts_is_not_moved_by_a_forged_ledger(repo: Path) -> None:
    _leak(repo, "a.py")
    _stop(repo, {"session_id": "s1", "loop_count": 0})
    _ledger(repo).open("a").write(_fake(reentry=CAP, verdict="block", findings=[], anchor=True))
    assert _denied(_stop(repo, {"session_id": "s1", "loop_count": 1}))


def test_a_deleted_ledger_is_refused_and_logged_untracked(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CHOCK_GATE_LOG")
    _leak(repo, "a.py")
    _stop(repo, {"session_id": "s1"})
    _ledger(repo).unlink()
    assert _denied(_stop(repo, {"session_id": "s1", "stop_hook_active": True}))
    assert [(r["verdict"], r["reentry_verdict"]) for r in _reentry_log(repo)] == [("block", "untracked")]
    for _ in range(CAP - 1):
        assert _denied(_stop(repo, {"session_id": "s1", "stop_hook_active": True}))
    assert _warned(_stop(repo, {"session_id": "s1", "stop_hook_active": True})), "counting resumes from there"


def test_a_ledger_directory_warns_at_once_for_a_client_that_cannot_count(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`stop_hook_active` proves one refusal already; with nowhere to count, the next could never end."""
    monkeypatch.delenv("CHOCK_GATE_LOG")
    _leak(repo, "a.py")
    _ledger(repo).mkdir(parents=True)
    assert _denied(_stop(repo, {"session_id": "s1"}))
    decision = _stop(repo, {"session_id": "s1", "stop_hook_active": True})
    assert _warned(decision) and "could not be written" in decision[1]
    (record,) = _reentry_log(repo)
    assert (record["verdict"], record["reentry_verdict"], record["would_block"]) == ("warn", "untracked", True)


@pytest.mark.parametrize("client", sorted(SIGNALS))
def test_an_unwritable_ledger_never_allows_silently(repo: Path, client: str) -> None:
    (repo / ".chock" / "state").write_text("not a directory", encoding="utf-8")
    _leak(repo, "a.py")
    signal = SIGNALS[client]
    assert _denied(_stop(repo, signal(0)))
    if client == "loop_count":
        for i in range(1, CAP + 1):
            assert _denied(_stop(repo, signal(i))), "the client's own count still bounds the refusals"
    assert _warned(_stop(repo, signal(CAP + 1)))


def test_a_vendor_turn_id_keys_the_count(repo: Path) -> None:
    """Codex's `turn_id`: another turn's records, even interleaved, are not this turn's."""
    _leak(repo, "a.py")
    t1 = {"session_id": "s1", "turn_id": "t1"}
    t2 = {"session_id": "s1", "turn_id": "t2"}
    _stop(repo, t1)
    _stop(repo, t2)
    for _ in range(CAP):
        assert _denied(_stop(repo, {**t1, "stop_hook_active": True}))
    assert _denied(_stop(repo, {**t2, "stop_hook_active": True})), "t2 has its own count"
    assert _warned(_stop(repo, {**t1, "stop_hook_active": True}))
    records = [json.loads(line) for line in _ledger(repo).read_text(encoding="utf-8").splitlines()]
    assert {r["turn"] for r in records} == {"t1", "t2"}


def test_the_ledger_is_bounded(repo: Path) -> None:
    _leak(repo, "a.py")
    path = _ledger(repo)
    path.parent.mkdir(parents=True)
    path.write_text(_fake(reentry=0, verdict="allow", findings=[]) * 600, encoding="utf-8")
    _stop(repo, {"session_id": "s1"})
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == stop_reentry.SESSION_MAX_ENTRIES and json.loads(lines[-1])["verdict"] == "block"


def test_a_record_for_another_session_does_not_count(repo: Path) -> None:
    _leak(repo, "a.py")
    _stop(repo, {"session_id": "s1"})
    _ledger(repo).open("a").write(_fake(reentry=CAP, verdict="block", findings=[], session_id="other"))
    assert _denied(_stop(repo, {"session_id": "s1", "stop_hook_active": True}))
