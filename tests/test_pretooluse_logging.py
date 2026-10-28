"""Outcome logging for the per-agent vendored runtimes' guard-running logic, through a real hook call."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from decision_log_support import (
    ASKING_GUARD,
    BLOCKING_GUARD,
    CLEAN_GUARD,
    POLICY,
    hook_env,
    records,
    run_hook,
    sync_layout,
    sync_log,
)

from chock.gate import budget, guard_runner, runner
from chock.gate.runner import journal

SECRET_COMMAND = 'curl -H "Authorization: Bearer sk-live-abcdef1234567890" https://example.invalid'


@pytest.fixture
def home(tmp_path: Path) -> Path:
    folder = tmp_path / "home"
    folder.mkdir()
    return folder


def test_block_is_recorded(tmp_path: Path, home: Path) -> None:
    repo, runtime, guard = sync_layout(tmp_path, BLOCKING_GUARD)

    proc = run_hook(repo, runtime, guard, "rm -rf /", hook_env(home))

    assert '"deny"' in proc.stdout
    [record] = records(sync_log(repo))
    assert record["policy_id"] == POLICY
    assert record["surface"] == "pre-tool-use"
    assert record["event"] == "tool_use"
    assert record["route"] == "sync"
    assert record["agent"] == "claude_code"
    assert record["verdict"] == "block"
    assert record["reason"] == "guard-blocked"
    assert record["level"] == "info"


def test_an_allow_is_an_info_line_with_only_a_fingerprint(tmp_path: Path, home: Path) -> None:
    """GAP-2 option B: every allowed tool call is logged at info, naming what was run, never its arguments."""
    repo, runtime, guard = sync_layout(tmp_path, CLEAN_GUARD)

    run_hook(repo, runtime, guard, "ls -la", hook_env(home))
    [record] = records(sync_log(repo))
    assert (record["verdict"], record["level"], record["reason"]) == ("allow", "info", "no-rule")
    assert record["target"] == "ls sha256:" + hashlib.sha256(b"ls -la").hexdigest()
    assert "trace" not in record

    run_hook(repo, runtime, guard, "ls -la", hook_env(home, CHOCK_LOG_LEVEL="off"))
    assert len(records(sync_log(repo))) == 1


def test_ask_is_recorded(tmp_path: Path, home: Path) -> None:
    """A deliberate ask is its own verdict in the log, not a block."""
    repo, runtime, guard = sync_layout(tmp_path, ASKING_GUARD)

    proc = run_hook(repo, runtime, guard, "rm -rf ./build", hook_env(home))

    assert "confirm the target" in proc.stdout
    [record] = records(sync_log(repo))
    assert (record["verdict"], record["reason"]) == ("ask", "guard-asked")


def test_a_guard_fault_is_recorded_as_one(tmp_path: Path, home: Path) -> None:
    """Exit 2 from a guard is a fault: an info line saying so, never a pass."""
    repo, runtime, guard = sync_layout(tmp_path, "#!/usr/bin/env bash\nexit 2\n")

    run_hook(repo, runtime, guard, "ls -la", hook_env(home))

    [record] = records(sync_log(repo))
    assert (record["verdict"], record["reason"]) == ("ask", "guard-errored")


def test_command_never_reaches_the_info_log(tmp_path: Path, home: Path) -> None:
    """Commands carry credentials far more often than files do."""
    repo, runtime, guard = sync_layout(tmp_path, BLOCKING_GUARD)

    run_hook(repo, runtime, guard, SECRET_COMMAND, hook_env(home))

    written = sync_log(repo).read_text(encoding="utf-8")
    assert "sk-live-abcdef1234567890" not in written
    for argument in ("Authorization", "Bearer", "example.invalid"):
        assert argument not in written
    [record] = records(sync_log(repo))
    assert record["target"] == "curl sha256:" + hashlib.sha256(SECRET_COMMAND.encode()).hexdigest()


@pytest.mark.parametrize("levels", [{"CHOCK_GATE_LOG": "0"}, {"CHOCK_LOG_LEVEL": "off"}], ids=["legacy", "level"])
def test_env_switch_disables_logging(tmp_path: Path, home: Path, levels: dict[str, str]) -> None:
    repo, runtime, guard = sync_layout(tmp_path, BLOCKING_GUARD)

    proc = run_hook(repo, runtime, guard, "rm -rf /", hook_env(home, **levels))

    assert '"deny"' in proc.stdout
    assert records(sync_log(repo)) == []


def test_logging_failure_does_not_change_the_verdict(tmp_path: Path, home: Path) -> None:
    repo, runtime, guard = sync_layout(tmp_path, BLOCKING_GUARD)
    sync_log(repo).mkdir(parents=True)  # a folder where the log file goes: every write fails

    proc = run_hook(repo, runtime, guard, "rm -rf /", hook_env(home, CHOCK_LOG_LEVEL="debug"))

    assert proc.returncode == 0
    assert '"permissionDecision": "deny"' in proc.stdout
    assert "Traceback" not in proc.stderr


def test_unparseable_command_still_runs_the_guard(tmp_path: Path) -> None:
    """Real run_guard, no stubbing: a parse failure hands the guard the raw command, not an ask."""
    guard = tmp_path / "implementations" / "clean.sh"
    guard.parent.mkdir()
    guard.write_text(CLEAN_GUARD, encoding="utf-8", newline="\n")

    assert guard_runner.run_guard(guard, 'echo "unbalanced') == guard_runner.GUARD_CLEAN
    assert guard_runner.evaluate(["--guard", str(guard)], 'echo "unbalanced', "Bash") is None


HANGING_GUARD = "#!/usr/bin/env bash\nsleep 30\n"


def test_a_timed_out_guard_does_not_echo_the_command_to_stderr(
    tmp_path: Path, monkeypatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The log's redaction rule applies to stderr too, and the timeout branch broke it."""
    guard = tmp_path / "implementations" / "hang.sh"
    guard.parent.mkdir()
    guard.write_text(HANGING_GUARD, encoding="utf-8", newline="\n")
    monkeypatch.setattr(budget, "ENGINE_BUDGET_SECONDS", 1)

    verdict = guard_runner.run_guard(guard, SECRET_COMMAND)
    assert verdict == guard_runner.GUARD_ERRORED, "a timeout is the guard failing to decide, not a precondition"

    err = capsys.readouterr().err
    assert "sk-live-abcdef1234567890" not in err, "a timing-out guard must not echo the credential"
    assert "Bearer" not in err
    assert "example.invalid" not in err, "nor the rest of the command it was gating"
    assert "timed out" in err, "and it must still say what happened"


def test_both_vendored_runners_agree_on_the_log_contract() -> None:
    """gate.py and every runtime carry the one journal; the legacy switch name is the same everywhere."""
    assert journal.LOG_LEGACY_ENV == runner.GATE_LOG_ENV
    assert journal.LOG_DEFAULT_MAX_BYTES == runner._LOG_MAX_BYTES
