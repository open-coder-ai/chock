"""A closed pager must stop the output, never the work.

`chock sync --repo . | head -2` exited 1 and left the repository unusable. The
compile itself was fine; `head` closed the pipe after two lines, the next `print` raised
`BrokenPipeError`, and the process died *between* installing the git hooks and refreshing the
registry and INDEX.md those hooks validate against. Every subsequent commit then failed with
`registry_freshness: Registry is stale`.

So the documented install flow bricked the repo whenever anyone piped it through `head`,
`grep -m1`, or a pager they quit early -- all ordinary things to do to a chatty command, and
none of them a mistake.

The conventional Unix fix, restoring `SIGPIPE` to `SIG_DFL` so the process dies quietly, is
wrong for a mutating command: dying quietly mid-way *is* the failure. Writes are made
non-fatal instead.

Found by the clean-venv adopter dry run, not by the test suite -- which is the argument for
keeping that dry run a release ritual.
"""

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
    """Only a broken pipe is survivable. A full disk must not be swallowed.

    Blanket `except OSError` here would turn "the write failed" into silence for every cause,
    including the ones where the caller genuinely needs to know.
    """
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

    # Never touches fd 1 when the reader is still there.
    silence_interpreter_flush(writer)


def _run_piped(args: list[str], cwd: Path) -> tuple[int, str]:
    """Run the CLI into `head -1` and report the CLI's exit code, not head's.

    A real shell pipeline rather than wiring two Popen objects together: this is the shape the
    bug actually takes, and `PIPESTATUS[0]` is the only way to see the upstream status, which
    is precisely the thing `head` hides from anyone reporting the problem.
    """
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
    """The actual defect: state-changing work sequenced after output that nobody is reading.

    A short command cannot reproduce this -- its whole output fits the 64 KiB pipe buffer, so
    no write ever fails and the test passes with or without the fix. `recompile` reproduces it
    because it prints hook-installation lines, then does the registry and INDEX bookkeeping
    those hooks depend on. Kill it in between and the repo is left failing validation on every
    commit.

    Asserting on `validate` rather than on the exit code alone is the point: exit 0 with a
    stale registry would still be the bug.
    """
    subprocess.run(["git", "init", "--quiet", "."], cwd=tmp_path, check=True)
    subprocess.run([sys.executable, "-m", "chock", "init", "."], cwd=tmp_path, capture_output=True, check=True)

    policy = tmp_path / ".agents" / "policies" / "pipe-demo"
    policy.mkdir(parents=True, exist_ok=True)
    (policy / "manifest.yaml").write_text(POLICY, encoding="utf-8")

    code, err = _run_piped(["recompile", "--repo", "."], tmp_path)
    assert code == 0, f"recompile exited {code} because stdout closed early; stderr:\n{err}"
    assert "BrokenPipeError" not in err, f"interpreter shutdown leaked a traceback:\n{err}"

    # Asserted on `registry_freshness` specifically, not on validate's exit code. This minimal
    # fixture policy legitimately fails other checks -- no evals, no lifecycle block -- and a
    # bare `returncode == 0` would conflate an incomplete fixture with the defect under test.
    check = subprocess.run(
        [sys.executable, "-m", "chock", "validate", "."], cwd=tmp_path, capture_output=True, text=True
    )
    output = check.stdout + check.stderr
    assert "registry_freshness" not in output, (
        "recompile's output was cut short and it never refreshed the registry, so the hooks it "
        f"just installed now fail every commit:\n{output}"
    )
    assert "index_freshness" not in output, f"INDEX.md was left stale by the truncated run:\n{output}"
