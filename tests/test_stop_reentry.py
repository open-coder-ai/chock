"""A client that re-enters the Stop hook in one turn is judged again, never waved through and never looped.

Claude Code, Codex and Copilot send `stop_hook_active`; Cursor sends `loop_count`. While findings remain,
every re-entry is refused up to the cap; past it the turn ends with a warning and a held gate-log
record. The ledger's own integrity is in test_stop_reentry_ledger.py, the wire in test_stop_reentry_wire.py.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from conftest import init_repo

from chock.gate import stop_reentry, write_gate
from chock.gate.assemble import runner_source

SECRET = "AKIA" + "1234567890ABCDEF"  # pragma: allowlist secret
OTHER = "AKIA" + "ZZZZZZZZZZZZZZZZ"  # pragma: allowlist secret
SPEC = {
    "kind": "content_regex",
    "on": ["commit", "tool_use"],
    "action": "block",
    "message": "secret-shaped string",
    "params": {"scan": "added_lines", "content_pattern": r"AKIA[0-9A-Z]{16}"},
}
CAP = stop_reentry.REENTRY_CAP

#: How each client marks the i-th Stop of a turn (0 is the first).
SIGNALS = {
    "stop_hook_active": lambda i: {"session_id": "s1", "stop_hook_active": bool(i)},
    "loop_count": lambda i: {"session_id": "s1", "loop_count": i},
}


@pytest.fixture(params=sorted(SIGNALS))
def signal(request: pytest.FixtureRequest):
    return SIGNALS[request.param]


def make_repo(tmp_path: Path) -> Path:
    """A repository with the `leaky` Stop gate compiled and the runner vendored beside it."""
    init_repo(tmp_path)
    gate = tmp_path / ".chock" / "compiled" / "leaky" / "stop" / "gate.json"
    gate.parent.mkdir(parents=True)
    gate.write_text(json.dumps(SPEC), encoding="utf-8")
    runner = tmp_path / ".chock" / "bin" / "gate.py"
    runner.parent.mkdir(parents=True)
    runner.write_text(runner_source(), encoding="utf-8")
    return tmp_path


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    return make_repo(tmp_path)


def _leak(repo: Path, name: str, extra: str = "") -> None:
    (repo / name).write_text(f'key = "{SECRET}"\n{extra}', encoding="utf-8")


def _stop(repo: Path, raw: dict):
    gate = repo / ".chock" / "compiled" / "leaky" / "stop" / "gate.json"
    return write_gate.evaluate_gate(["--gate", str(gate)], SimpleNamespace(event="stop", raw=raw, cwd=str(repo)))


def _denied(decision) -> bool:
    return decision is not None and decision[0] == write_gate.VERDICT_DENY


def _warned(decision) -> bool:
    return decision is not None and decision[0] == "warn"


def _reentry_log(repo: Path) -> list[dict]:
    path = repo / ".chock" / "log" / "gate-events.jsonl"
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    return [r for r in map(json.loads, lines) if r.get("kind") == "reentry"]


def test_the_first_stop_of_a_turn_refuses(repo: Path, signal) -> None:
    _leak(repo, "a.py")
    decision = _stop(repo, signal(0))
    assert _denied(decision) and "a.py" in decision[1]


def test_a_re_entry_with_the_same_findings_is_refused_again(repo: Path, signal) -> None:
    """Stopping again changes nothing on disk: the turn may not end on that alone."""
    _leak(repo, "a.py")
    assert _denied(_stop(repo, signal(0)))
    for i in range(1, CAP + 1):
        assert _denied(_stop(repo, signal(i))), f"re-entry {i} still has the secret on disk"


def test_a_re_entry_with_a_new_violation_is_refused(repo: Path, signal) -> None:
    _leak(repo, "a.py")
    assert _denied(_stop(repo, signal(0)))
    _leak(repo, "b.py")
    decision = _stop(repo, signal(1))
    assert _denied(decision) and "b.py" in decision[1]


def test_the_cap_ends_the_turn_with_a_warning_never_silently(repo: Path, signal) -> None:
    _leak(repo, "a.py")
    assert _denied(_stop(repo, signal(0)))
    for i in range(1, CAP + 1):
        decision = _stop(repo, signal(i))
        assert _denied(decision)
    assert "still on disk" in decision[1] and "commit will refuse" in decision[1], "the last refusal says what is next"
    warned = _stop(repo, signal(CAP + 1))
    assert _warned(warned), "past the cap the turn ends, with a warning"
    text = warned[1]
    assert "still on disk" in text and "commit will refuse" in text and "a person must review" in text
    assert "a.py" in text and f"after {CAP} refused stops" in text
    assert "(unchanged since the last refusal)" in text


def test_the_cap_warning_says_when_the_findings_changed(repo: Path, signal) -> None:
    _leak(repo, "a.py")
    for i in range(CAP + 1):
        _stop(repo, signal(i))
    _leak(repo, "b.py")
    assert "(changed since the last refusal)" in _stop(repo, signal(CAP + 1))[1]


def test_the_cap_warning_reaches_stderr_for_clients_with_no_warning_field(repo: Path, signal, capsys) -> None:
    _leak(repo, "a.py")
    for i in range(CAP + 1):
        _stop(repo, signal(i))
    capsys.readouterr()
    _stop(repo, signal(CAP + 1))
    assert "still on disk" in capsys.readouterr().err


def test_the_cap_is_a_held_record_in_the_gate_log_even_with_the_log_off(repo: Path, signal) -> None:
    """`CHOCK_GATE_LOG=0` (the suite's default) keeps the rest out; the held warn is the evidence."""
    _leak(repo, "a.py")
    for i in range(CAP + 2):
        _stop(repo, signal(i))
    (record,) = _reentry_log(repo)
    assert record["verdict"] == "warn" and record["would_block"] is True and record["would_action"] == "block"
    assert record["reentry"] == CAP + 1 and record["reentry_verdict"] == "cap-reached"
    assert (
        record["policy_id"] == "leaky" and record["surface"] == "stop-reentry" and record["findings_changed"] is False
    )


def test_an_earlier_re_entry_does_not_announce_the_end(repo: Path, signal) -> None:
    _leak(repo, "a.py")
    assert _denied(_stop(repo, signal(0)))
    assert "still on disk" not in _stop(repo, signal(1))[1]


def test_a_clean_turn_is_allowed_at_the_first_stop_and_on_re_entry(repo: Path, signal) -> None:
    (repo / "fine.py").write_text("x = 1\n", encoding="utf-8")
    assert _stop(repo, signal(0)) is None
    assert _stop(repo, signal(1)) is None


def test_a_violation_fixed_after_the_refusal_is_allowed(repo: Path, signal) -> None:
    _leak(repo, "a.py")
    assert _denied(_stop(repo, signal(0)))
    (repo / "a.py").unlink()
    assert _stop(repo, signal(1)) is None


def test_the_next_turn_is_judged_afresh(repo: Path, signal) -> None:
    _leak(repo, "a.py")
    for i in range(CAP + 2):
        _stop(repo, signal(i))
    assert _denied(_stop(repo, signal(0))), "a first stop is never waved through"
    assert _denied(_stop(repo, signal(1))), "and the new turn has its own count"


def test_the_ledger_keeps_digests_and_never_file_contents(repo: Path, signal) -> None:
    _leak(repo, "a.py")
    _stop(repo, signal(0))
    _stop(repo, signal(1))
    text = (repo / ".chock" / "state" / "s1.stop.jsonl").read_text(encoding="utf-8")
    assert '"phase": "stop"' in text and SECRET not in text and "a.py" not in text


def test_stop_records_stay_out_of_the_tool_call_session_log(repo: Path, signal) -> None:
    """spec/session-log.md's `<session_id>.jsonl` holds `pre`/`post` records only."""
    _leak(repo, "a.py")
    _stop(repo, signal(0))
    _stop(repo, signal(1))
    assert not (repo / ".chock" / "state" / "s1.jsonl").exists()


def test_a_second_secret_in_a_flagged_file_is_a_changed_finding(repo: Path) -> None:
    _leak(repo, "a.py")
    first = stop_reentry.finding_digests("x\n  - a.py: p", {"a.py": (repo / "a.py").read_text(encoding="utf-8")})
    _leak(repo, "a.py", f'k2 = "{OTHER}"\n')
    second = stop_reentry.finding_digests("x\n  - a.py: p", {"a.py": (repo / "a.py").read_text(encoding="utf-8")})
    assert first != second, "same path, same wording, different content"


def test_a_second_secret_in_a_flagged_file_is_refused_and_logged_as_changed(
    repo: Path, signal, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("CHOCK_GATE_LOG")
    _leak(repo, "a.py")
    assert _denied(_stop(repo, signal(0)))
    _leak(repo, "a.py", f'k2 = "{OTHER}"\n')
    assert _denied(_stop(repo, signal(1)))
    assert [r["findings_changed"] for r in _reentry_log(repo)] == [True]


def test_findings_digests_ignore_an_unflagged_file(repo: Path) -> None:
    writes = {"a.py": "secret", "fine.py": "x = 1"}
    before = stop_reentry.finding_digests("m\n  - a.py: p", writes)
    assert before == stop_reentry.finding_digests("m\n  - a.py: p", {**writes, "fine.py": "x = 2"})


def test_every_re_entry_verdict_reaches_the_gate_log_in_status_words(
    repo: Path, signal, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("CHOCK_GATE_LOG")
    _leak(repo, "a.py")
    _stop(repo, signal(0))
    _stop(repo, signal(1))
    _leak(repo, "b.py")
    _stop(repo, signal(2))
    (repo / "a.py").unlink()
    (repo / "b.py").unlink()
    _stop(repo, signal(3))
    got = [(r["reentry"], r["verdict"], r["reentry_verdict"], r.get("findings_changed")) for r in _reentry_log(repo)]
    assert got == [(1, "block", "refused", False), (2, "block", "refused", True), (3, "allow", "clean", None)]


def test_a_first_stop_writes_no_re_entry_record(repo: Path, signal, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CHOCK_GATE_LOG")
    _leak(repo, "a.py")
    _stop(repo, signal(0))
    assert _reentry_log(repo) == []


def test_a_count_the_client_sends_is_trusted_over_the_ledger(repo: Path) -> None:
    """Cursor says how often it re-entered: a cleared ledger cannot restart the count, nor a padded one end it."""
    _leak(repo, "a.py")
    assert _denied(_stop(repo, {"session_id": "s1", "loop_count": CAP}))
    assert _warned(_stop(repo, {"session_id": "s1", "loop_count": CAP + 1}))
