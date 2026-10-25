"""A gate pattern cannot hang a hook or fail it open: every pattern runs under a deadline, on every platform.

`re` holds the GIL and nothing can interrupt it in-process, so the patterns run in a child the
engine kills at the deadline (chock.gate.budget). The git hook, the in-agent write path, the
tool_call path and the history scan all refuse naming the gate; none waits past the deadline.
"""

from __future__ import annotations

import ast
import json
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from conftest import init_repo, stage

from chock.gate import budget, tool_call_gate, write_gate
from chock.gate.assemble import runner_source
from chock.gate.gate_outcome import GATE_ERRORED, gate_decision
from chock.gate.runner import kinds, run
from chock.history import scan

POLICY = "redos-gate"
REDOS = r"^(a+)+$"
LINE = "a" * 60 + "!\n"
SECONDS = 1
SPEC = {"kind": "content_regex", "on": ["commit", "tool_use"], "action": "block", "message": "m", "params": {}}


def _vendored(seconds: int = SECONDS) -> str:
    """The runner as `chock sync` vendors it, with the pattern deadline cut to `seconds`."""
    source = runner_source()
    assert f"\nPATTERN_SECONDS = {budget.PATTERN_SECONDS}\n" in source
    return source.replace(f"\nPATTERN_SECONDS = {budget.PATTERN_SECONDS}\n", f"\nPATTERN_SECONDS = {seconds}\n", 1)


def _installed(repo: Path, surface: str, pattern: str = REDOS) -> Path:
    """A compiled content gate on `surface` and the vendored runner, laid out as `chock sync` leaves them."""
    gate = repo / ".chock" / "compiled" / POLICY / surface / "gate.json"
    gate.parent.mkdir(parents=True, exist_ok=True)
    gate.write_text(json.dumps({**SPEC, "params": {"content_pattern": pattern}}), encoding="utf-8")
    runner = repo / ".chock" / "bin" / "gate.py"
    runner.parent.mkdir(parents=True, exist_ok=True)
    runner.write_text(_vendored(), encoding="utf-8", newline="\n")
    return gate


def test_the_git_path_exits_2_within_the_deadline_naming_the_gate(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    gate = _installed(repo, "git-hook")
    stage(repo, "a.txt", LINE)
    started = time.monotonic()
    proc = subprocess.run(
        [sys.executable, str(repo / ".chock" / "bin" / "gate.py"), "run", "--gate", str(gate), "--event", "pre-commit"],
        cwd=repo,
        capture_output=True,
        text=True,
        timeout=budget.PATTERN_SECONDS,
        check=False,
    )
    assert time.monotonic() - started < budget.PATTERN_SECONDS
    assert proc.returncode == 2, proc.stderr
    assert f"gate: {POLICY}: the patterns gave no verdict within {SECONDS}s" in proc.stderr
    assert "catastrophic pattern" in proc.stderr and "refusing rather than allowing" in proc.stderr


def test_a_sane_pattern_on_the_same_line_still_blocks(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    gate = _installed(repo, "git-hook", pattern="!")
    stage(repo, "a.txt", LINE)
    proc = subprocess.run(
        [sys.executable, str(repo / ".chock" / "bin" / "gate.py"), "run", "--gate", str(gate), "--event", "pre-commit"],
        cwd=repo,
        capture_output=True,
        text=True,
        timeout=budget.PATTERN_SECONDS,
        check=False,
    )
    assert proc.returncode == 1 and "a.txt" in proc.stderr


def test_the_in_package_runner_refuses_the_same_way(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    repo = init_repo(tmp_path)
    gate = _installed(repo, "git-hook")
    stage(repo, "a.txt", LINE)
    monkeypatch.setattr(kinds, "PATTERN_SECONDS", SECONDS)
    assert run(gate, "pre-commit", None, repo) == 2
    err = capsys.readouterr().err
    assert f"gate: {POLICY}: the patterns gave no verdict within {SECONDS}s" in err


def test_the_write_path_refuses_naming_the_gate(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    gate = _installed(repo, "pre-tool-use")
    outcome, message = write_gate.run_gate(gate, {"a.txt": LINE}, "pre-tool-use", (repo, {}), budget.engine_deadline())
    assert outcome == GATE_ERRORED
    assert f"gate: {POLICY}: the patterns gave no verdict within {SECONDS}s" in message
    verdict, spoken = gate_decision(outcome, message, gate)
    assert verdict == "deny" and POLICY in spoken


def test_the_tool_call_path_refuses_naming_the_gate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = init_repo(tmp_path)
    gate = repo / ".chock" / "compiled" / POLICY / "pre-tool-use" / "tool-call-gate.json"
    gate.parent.mkdir(parents=True)
    spec = {
        "kind": "content_regex",
        "on": ["tool_call"],
        "action": "block",
        "params": {"content_pattern": r'(a+)+"', "tools": ["Bash"]},  # judged as JSON text: quoted, in braces
    }
    gate.write_text(json.dumps(spec), encoding="utf-8")
    monkeypatch.setattr(tool_call_gate, "PATTERN_SECONDS", SECONDS)
    event = SimpleNamespace(
        event="pre_tool", tool="Bash", raw={"tool_input": {"command": "a" * 60 + "!"}}, cwd=str(repo)
    )
    started = time.monotonic()
    verdict = tool_call_gate.evaluate_tool_call(["--tool-call", str(gate)], event)
    assert time.monotonic() - started < budget.PATTERN_SECONDS
    assert verdict is not None and verdict[0] == "deny"
    assert f"content_regex gate {POLICY}: the patterns gave no verdict within {SECONDS}s" in verdict[1]
    assert "refusing rather than allowing" in verdict[1]
    event.raw = {"tool_input": {"command": "aaa"}}
    assert tool_call_gate.evaluate_tool_call(["--tool-call", str(gate)], event) == (
        "deny",
        "blocked by a chock tool_call gate",
    )
    event.raw = {"tool_input": {"command": "b"}}
    assert tool_call_gate.evaluate_tool_call(["--tool-call", str(gate)], event) is None


def test_the_history_scan_needs_no_signal() -> None:
    """The scan's deadline is the judge's, not SIGALRM's: Windows is bounded the same way."""
    tree = ast.parse(Path(scan.__file__).read_text(encoding="utf-8"))
    imported = {alias.name for node in tree.body if isinstance(node, ast.Import) for alias in node.names}
    assert "signal" not in imported and "threading" not in imported
    assert scan.BLOB_SECONDS == budget.PATTERN_SECONDS


def test_the_judge_matches_times_out_and_reports_a_dead_child() -> None:
    judge = budget.pattern_judge()
    assert budget.judge_patterns(judge, [("a", []), ("b", [])], SECONDS) == ([[], []], None)
    assert judge["proc"] is None, "nothing to judge starts no child"
    assert budget.judge_patterns(judge, [("a+", ["xa", "b", "aaa"]), (r"\d", ["1", "x"])], SECONDS) == (
        [[0, 2], [0]],
        None,
    )
    started = time.monotonic()
    hits, why = budget.judge_patterns(judge, [(REDOS, [LINE])], SECONDS)
    assert hits is None and why == f"the patterns gave no verdict within {SECONDS}s (a catastrophic pattern?)"
    assert SECONDS <= time.monotonic() - started < budget.PATTERN_SECONDS
    assert judge["proc"] is None, "a timed-out child is killed"
    hits, why = budget.judge_patterns(judge, [("(", ["x"])], SECONDS)
    assert hits is None and why.startswith("the pattern judge exited early (")
    assert budget.judge_patterns(judge, [("x", ["x"])], SECONDS) == ([[0]], None), "a new child after a crash"
    assert budget.close_judge(judge) == "" and judge["proc"] is None


def test_the_judge_keeps_text_whole_across_the_pipe() -> None:
    judge = budget.pattern_judge()
    texts = ["café ☃", "a\nb", "lone \udcff surrogate", "tab\there", '"quoted" \\ back']
    try:
        assert budget.judge_patterns(judge, [("☃|\udcff|\\\\ back|^a$", texts)], budget.PATTERN_SECONDS) == (
            [[0, 2, 4]],
            None,
        )
    finally:
        budget.close_judge(judge)


def test_the_judges_start_up_is_not_charged_to_the_patterns_deadline(tmp_path: Path) -> None:
    slow = tmp_path / "slow-python"
    slow.write_text(f'#!/bin/sh\nsleep 1.5\nexec "{sys.executable}" "$@"\n', encoding="utf-8")
    slow.chmod(0o755)
    judge = budget.pattern_judge(str(slow))
    try:
        assert budget.judge_patterns(judge, [("a+", ["xa", "b"])], 1) == ([[0]], None)
    finally:
        budget.close_judge(judge)
