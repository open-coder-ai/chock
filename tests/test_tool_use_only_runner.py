"""A gate declared only at tool_use still gets the runner its in-agent hooks call."""

from __future__ import annotations

from pathlib import Path

from test_pre_tool_use_gate import _policy

from chock.compile.emitters.in_agent import emit_pre_tool_use, emit_stop


def _runner(tmp_path: Path) -> Path:
    return tmp_path / ".chock" / "bin" / "gate.py"


def test_the_write_path_vendors_the_runner(tmp_path: Path) -> None:
    """No commit or push means no git hook, which used to be the only thing that vendored it."""
    policy, manifest = _policy(tmp_path, on=("tool_use",))
    emit_pre_tool_use(policy, tmp_path / ".chock" / "compiled" / "pinned" / "pre-tool-use", manifest)
    assert _runner(tmp_path).is_file()


def test_the_turn_end_vendors_the_runner(tmp_path: Path) -> None:
    policy, manifest = _policy(tmp_path, on=("tool_use",))
    emit_stop(policy, tmp_path / ".chock" / "compiled" / "pinned" / "stop", manifest)
    assert _runner(tmp_path).is_file()


def test_a_policy_with_no_tool_use_gate_vendors_nothing_here(tmp_path: Path) -> None:
    policy, manifest = _policy(tmp_path, on=("commit",))
    emit_pre_tool_use(policy, tmp_path / ".chock" / "compiled" / "pinned" / "pre-tool-use", manifest)
    assert not _runner(tmp_path).exists()
