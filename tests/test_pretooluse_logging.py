"""Outcome logging on the PreToolUse surface.

Two things differ from the gate runner and both are deliberate. The record carries no
command, because on this surface the command *is* the scanned content and routinely holds
bearer tokens. And "the guard could not run" is not an outcome: it allows, like a clean
run, but recording it as a pass would invent the evidence this log exists to collect.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from chock.gate import pretooluse, runner
from chock.gate.pretooluse import GATE_LOG_ENV, main, run_guard


@pytest.fixture(autouse=True)
def enable_gate_log(monkeypatch: pytest.MonkeyPatch) -> None:
    """Opt back in to the logging the suite-wide `no_gate_log` fixture switches off."""
    monkeypatch.delenv(GATE_LOG_ENV, raising=False)


BLOCKING_GUARD = "#!/usr/bin/env bash\nexit 1\n"
CLEAN_GUARD = "#!/usr/bin/env bash\nexit 0\n"
BROKEN_GUARD = "#!/usr/bin/env bash\nexit 42\n"

SECRET_COMMAND = 'curl -H "Authorization: Bearer sk-live-abcdef1234567890" https://example.invalid'


def make_guard(repo: Path, body: str, policy_id: str = "block-destructive-commands") -> Path:
    """A guard at the shape the emitter writes: <policy_id>/implementations/<name>.sh."""
    (repo / ".chock").mkdir(parents=True, exist_ok=True)
    guard = repo / ".agents" / "policies" / policy_id / "implementations" / "block-destructive.sh"
    guard.parent.mkdir(parents=True, exist_ok=True)
    guard.write_text(body, encoding="utf-8", newline="\n")
    return guard


def payload(command: str, tool: str = "Bash") -> str:
    return json.dumps({"tool_name": tool, "tool_input": {"command": command}})


def read_log(repo: Path) -> list[dict]:
    path = repo / ".chock" / "log" / "gate-events.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def run_main(guard: Path, command: str, monkeypatch, tool: str = "Bash") -> int:
    monkeypatch.setattr("sys.stdin", _Stdin(payload(command, tool)))
    return main(["--guard", str(guard)])


class _Stdin:
    def __init__(self, text: str) -> None:
        self._text = text

    def read(self) -> str:
        return self._text


def test_block_is_recorded(tmp_path: Path, monkeypatch) -> None:
    guard = make_guard(tmp_path, BLOCKING_GUARD)
    monkeypatch.setattr(pretooluse, "run_guard", lambda *_: True)

    assert run_main(guard, "rm -rf /", monkeypatch) == 2

    records = read_log(tmp_path)
    assert len(records) == 1
    assert records[0]["policy_id"] == "block-destructive-commands"
    assert records[0]["surface"] == "pre-tool-use"
    assert records[0]["event"] == "tool_use"
    assert records[0]["kind"] == "block-destructive"
    assert records[0]["tool"] == "Bash"
    assert records[0]["verdict"] == "block"


def test_allow_is_recorded(tmp_path: Path, monkeypatch) -> None:
    guard = make_guard(tmp_path, CLEAN_GUARD)
    monkeypatch.setattr(pretooluse, "run_guard", lambda *_: False)

    assert run_main(guard, "ls -la", monkeypatch) == 0

    assert read_log(tmp_path)[0]["verdict"] == "allow"


def test_unchecked_guard_is_not_recorded_as_a_pass(tmp_path: Path, monkeypatch) -> None:
    """The distinction the tri-state exists for: allowed, but nothing was checked."""
    guard = make_guard(tmp_path, BROKEN_GUARD)
    monkeypatch.setattr(pretooluse, "run_guard", lambda *_: None)

    assert run_main(guard, "ls -la", monkeypatch) == 0
    assert read_log(tmp_path) == []


def test_command_never_reaches_the_log(tmp_path: Path, monkeypatch) -> None:
    """Commands carry credentials far more often than files do."""
    guard = make_guard(tmp_path, BLOCKING_GUARD)
    monkeypatch.setattr(pretooluse, "run_guard", lambda *_: True)

    run_main(guard, SECRET_COMMAND, monkeypatch)

    written = (tmp_path / ".chock" / "log" / "gate-events.jsonl").read_text(encoding="utf-8")
    assert "sk-live-abcdef1234567890" not in written
    assert "curl" not in written


def test_env_switch_disables_logging(tmp_path: Path, monkeypatch) -> None:
    guard = make_guard(tmp_path, BLOCKING_GUARD)
    monkeypatch.setattr(pretooluse, "run_guard", lambda *_: True)
    monkeypatch.setenv(GATE_LOG_ENV, "0")

    assert run_main(guard, "rm -rf /", monkeypatch) == 2
    assert read_log(tmp_path) == []


def test_logging_failure_does_not_change_the_verdict(tmp_path: Path, monkeypatch) -> None:
    guard = make_guard(tmp_path, BLOCKING_GUARD)
    monkeypatch.setattr(pretooluse, "run_guard", lambda *_: True)

    class Exploding:
        @staticmethod
        def now(*args, **kwargs):
            raise OSError("log device on fire")

    monkeypatch.setattr(pretooluse, "datetime", Exploding)

    assert run_main(guard, "rm -rf /", monkeypatch) == 2
    assert read_log(tmp_path) == []


def test_guard_outside_an_chock_repo_is_not_recorded(tmp_path: Path, monkeypatch) -> None:
    guard = tmp_path / "loose" / "implementations" / "block-destructive.sh"
    guard.parent.mkdir(parents=True, exist_ok=True)
    guard.write_text(BLOCKING_GUARD, encoding="utf-8", newline="\n")
    monkeypatch.setattr(pretooluse, "run_guard", lambda *_: True)

    assert run_main(guard, "rm -rf /", monkeypatch) == 2
    assert read_log(tmp_path) == []


def test_unparseable_command_is_allowed_and_unrecorded(tmp_path: Path, monkeypatch) -> None:
    """Real run_guard, no stubbing: a parse failure must not masquerade as a clean check."""
    guard = make_guard(tmp_path, CLEAN_GUARD)

    assert run_guard(guard, 'echo "unbalanced') is None
    assert run_main(guard, 'echo "unbalanced', monkeypatch) == 0
    assert read_log(tmp_path) == []


def test_both_vendored_runners_agree_on_the_log_contract() -> None:
    """The two copies are deliberately duplicated; this is what keeps them one log.

    Neither file may import the other -- each is vendored standalone, and a PreToolUse-only
    repo never receives gate.py. So the shared constants are pinned here instead.
    """
    assert pretooluse.GATE_LOG_ENV == runner.GATE_LOG_ENV
    assert pretooluse._LOG_MAX_BYTES == runner._LOG_MAX_BYTES
