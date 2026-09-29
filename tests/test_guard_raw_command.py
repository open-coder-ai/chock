"""What a guard is handed when shlex cannot parse the command, and when exit 1 is a crash."""

from __future__ import annotations

import json
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from chock.gate import guard_runner, runtime_bundle

ENV_DUMP = 'printf "%s\\n" "$CHOCK_TOOL" "$CHOCK_RAW_COMMAND" "$CHOCK_ARGV_FALLBACK" "$#" > "$OUT"; exit 3'
POWERSHELL_COMMAND = "Remove-Item -Recurse C:\\"  # one trailing backslash: shlex raises on it


def make_guard(tmp_path: Path, body: str, name: str = "g.sh") -> Path:
    guard = tmp_path / name
    head = "" if name.endswith(".py") else "#!/usr/bin/env bash\n"
    guard.write_text(f"{head}{body}\n", encoding="utf-8", newline="\n")
    guard.chmod(guard.stat().st_mode | stat.S_IEXEC)
    return guard


def dump(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, command: str, tool: str = "") -> list[str]:
    out = tmp_path / "seen.txt"
    monkeypatch.setenv("OUT", str(out))
    guard = make_guard(tmp_path, ENV_DUMP)
    assert guard_runner.run_guard(guard, command, tool) == guard_runner.GUARD_ASKED
    return out.read_text(encoding="utf-8").split("\n")[:4]


@pytest.mark.parametrize("command", ["rm -rf /\\", 'echo "open', POWERSHELL_COMMAND, POWERSHELL_COMMAND + " '"])
def test_shlex_failure_still_runs_the_guard_with_the_raw_command(tmp_path, monkeypatch, command) -> None:
    tool, raw, fallback, argc = dump(tmp_path, monkeypatch, command)

    assert raw == command
    assert fallback == "1"
    assert int(argc) == len(command.split())


def test_powershell_remove_item_reaches_the_guard_as_powershell(tmp_path, monkeypatch) -> None:
    tool, raw, fallback, _ = dump(tmp_path, monkeypatch, POWERSHELL_COMMAND, "PowerShell")

    assert (tool, raw) == ("powershell", POWERSHELL_COMMAND)


def test_a_windows_path_survives_in_the_raw_command_and_the_fallback_argv(tmp_path, monkeypatch) -> None:
    command = r"type C:\x 'unclosed"
    _, raw, fallback, _ = dump(tmp_path, monkeypatch, command)

    assert raw == command
    assert guard_runner.split_command(command) == ([*command.split()], True)
    assert r"C:\x" in guard_runner.split_command(command)[0]


def test_a_parsable_command_keeps_the_exact_posix_argv(tmp_path, monkeypatch) -> None:
    _, _, fallback, argc = dump(tmp_path, monkeypatch, 'git commit -m "two words"')

    assert fallback == ""
    assert argc == "4"
    assert guard_runner.split_command("a 'b c'") == (["a", "b c"], False)


@pytest.mark.parametrize(
    ("tool", "expected"),
    [
        ("Bash", "bash"),
        ("bash", "bash"),
        ("PowerShell", "powershell"),
        ("pwsh", "powershell"),
        ("sh", "shell"),
        ("shell", "shell"),
        ("run_shell_command", "shell"),
        ("beforeShellExecution", "shell"),
        ("", "unknown"),
        (None, "unknown"),
        ("run_command", "unknown"),
    ],
)
def test_tool_names_normalize(tool, expected) -> None:
    assert guard_runner.normalize_tool(tool) == expected


def test_a_python_traceback_exiting_1_is_errored_not_blocked(tmp_path) -> None:
    guard = make_guard(tmp_path, "raise RuntimeError('boom')", "crash.py")

    assert guard_runner.run_guard(guard, "ls") == guard_runner.GUARD_ERRORED


@pytest.mark.parametrize("body", ["exit 1", "echo 'line 3: syntax error near unexpected token' >&2; exit 1"])
def test_silent_or_syntax_error_exit_1_is_errored(tmp_path, body) -> None:
    assert guard_runner.run_guard(make_guard(tmp_path, body), "ls") == guard_runner.GUARD_ERRORED


def test_exit_1_with_a_reason_still_blocks(tmp_path, capsys) -> None:
    guard = make_guard(tmp_path, "echo 'no force pushes' >&2; exit 1")

    assert guard_runner.run_guard_detailed(guard, "git push -f") == (guard_runner.GUARD_BLOCKED, "no force pushes")
    assert "no force pushes" in capsys.readouterr().err


def test_a_crashing_guard_asks_through_a_vendored_runtime(tmp_path) -> None:
    guard = make_guard(tmp_path, "raise SystemExit(1)\n", "silent.py")
    runtime = tmp_path / "claude_code.py"
    runtime.write_text(runtime_bundle.render("claude_code"), encoding="utf-8")
    payload = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": "ls"}}

    proc = subprocess.run(
        [sys.executable, str(runtime), "--guard", str(guard)],
        input=json.dumps(payload).encode(),
        capture_output=True,
        check=False,
    )

    assert json.loads(proc.stdout)["hookSpecificOutput"]["permissionDecision"] == "ask"
