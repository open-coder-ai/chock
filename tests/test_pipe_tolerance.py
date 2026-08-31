"""A closed pager must stop the output, never the work."""

from __future__ import annotations

import io
import shlex
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import WORKING_BASH, needs_bash

from chock.pipe import PipeTolerantWriter, guard_stdout, silence_interpreter_flush

ROOT = Path(__file__).resolve().parents[1]


class _ClosedPipe(io.StringIO):
    """A stream that fails the way a pipe with no reader does."""

    def write(self, text: str) -> int:
        raise BrokenPipeError(32, "Broken pipe")


class _RealFailure(io.StringIO):
    def write(self, text: str) -> int:
        raise OSError(28, "No space left on device")


def test_writes_survive_a_vanished_reader() -> None:
    writer = PipeTolerantWriter(_ClosedPipe())

    writer.write("first")
    writer.write("second")
    writer.flush()

    assert writer.closed_by_reader


def test_a_real_io_error_is_still_raised() -> None:
    """Only a broken pipe is survivable. A full disk must not be swallowed."""
    writer = PipeTolerantWriter(_RealFailure())

    with pytest.raises(OSError, match="No space left"):
        writer.write("anything")


def test_guard_restores_nothing_it_should_not(monkeypatch: pytest.MonkeyPatch) -> None:
    """`guard_stdout` swaps stdout and hands the wrapper back for the exit-time cleanup."""
    monkeypatch.setattr(sys, "stdout", io.StringIO())
    writer = guard_stdout()

    assert sys.stdout is writer
    print("routed through the wrapper")
    assert not writer.closed_by_reader

    silence_interpreter_flush(writer)


def _run_piped(args: list[str], cwd: Path) -> tuple[int, str]:
    """Run the CLI into `head -1` and report the CLI's exit code, not head's."""
    quoted = " ".join(shlex.quote(a) for a in [sys.executable, "-m", "chock", *args])
    proc = subprocess.run(
        [WORKING_BASH, "-c", f"{quoted} | head -1; exit ${{PIPESTATUS[0]}}"],
        cwd=cwd,
        capture_output=True,
        text=True,
    )
    return proc.returncode, proc.stderr


POLICY = """\
id: pipe-demo
name: Pipe Demo
version: "0.0.1"
description: Block direct commits to a protected branch.
artifact: hook
enforcement: block
effects: [read_only]
hook:
  gate:
    kind: forbidden_ref
    "on": [commit]
    action: block
    message: Direct commits to ({refs}) are blocked.
    params:
      refs: [main]
provenance:
  author: test
  source_repo: https://example.com
  license: Apache-2.0
  trust_tier: sandbox
"""


@needs_bash
def test_recompile_finishes_its_bookkeeping_when_the_reader_closes_early(tmp_path: Path) -> None:
    """The actual defect: state-changing work sequenced after output that nobody is reading."""
    subprocess.run(["git", "init", "--quiet", "."], cwd=tmp_path, check=True)
    subprocess.run([sys.executable, "-m", "chock", "init", "."], cwd=tmp_path, capture_output=True, check=True)

    policy = tmp_path / ".agents" / "policies" / "pipe-demo"
    policy.mkdir(parents=True, exist_ok=True)
    (policy / "manifest.yaml").write_text(POLICY, encoding="utf-8")

    code, err = _run_piped(["recompile", "--repo", "."], tmp_path)
    assert code == 0, f"recompile exited {code} because stdout closed early; stderr:\n{err}"
    assert "BrokenPipeError" not in err, f"interpreter shutdown leaked a traceback:\n{err}"

    check = subprocess.run(
        [sys.executable, "-m", "chock", "validate", "."], cwd=tmp_path, capture_output=True, text=True
    )
    output = check.stdout + check.stderr
    assert "registry_freshness" not in output, (
        "recompile's output was cut short and it never refreshed the registry, so the hooks it "
        f"just installed now fail every commit:\n{output}"
    )
    assert "index_freshness" not in output, f"INDEX.md was left stale by the truncated run:\n{output}"
