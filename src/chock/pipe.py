"""Keep a closed stdout from abandoning a command halfway through.

`chock sync --repo . | head -2` exited 1 and left the repository unusable: the
registry and `INDEX.md` were never refreshed, so the validate hook the same command had just
installed failed on every subsequent commit with `registry_freshness: Registry is stale`.

Nothing was wrong with the compile. `head` closed the pipe after two lines, the next `print`
raised `BrokenPipeError`, and the process died between installing hooks and doing the
bookkeeping that makes them usable. `| less` quit early, `| grep -m1` and `| head` are all
ordinary things to do to a chatty command, and each of them bricked the repo.

The usual Unix answer -- restore `SIGPIPE` to `SIG_DFL` and let the process die quietly -- is
wrong for a *mutating* command. Dying quietly mid-way is precisely the failure. So writes are
made non-fatal instead: once the reader is gone we stop printing and carry on working, because
the output was never the deliverable.
"""

from __future__ import annotations

import errno
import os
import sys
from typing import Any, TextIO


def _is_broken_pipe(exc: OSError) -> bool:
    return isinstance(exc, BrokenPipeError) or exc.errno in (errno.EPIPE, errno.EINVAL)


class PipeTolerantWriter:
    """Wrap a text stream so a vanished reader stops output rather than the program.

    Deliberately not an `io.TextIOBase` subclass: this only needs to stand in for the handful
    of attributes `print` and friends touch, and inheriting the ABC would invite callers to
    rely on stream behaviour that is not actually forwarded.
    """

    def __init__(self, stream: TextIO) -> None:
        self._stream = stream
        self.closed_by_reader = False

    def write(self, text: str) -> int:
        if self.closed_by_reader:
            return len(text)
        try:
            return self._stream.write(text)
        except OSError as exc:
            if not _is_broken_pipe(exc):
                raise
            self.closed_by_reader = True
            return len(text)

    def flush(self) -> None:
        if self.closed_by_reader:
            return
        try:
            self._stream.flush()
        except OSError as exc:
            if not _is_broken_pipe(exc):
                raise
            self.closed_by_reader = True

    def __getattr__(self, name: str) -> Any:
        return getattr(self._stream, name)


def guard_stdout() -> PipeTolerantWriter:
    """Install the wrapper on `sys.stdout` and return it."""
    writer = PipeTolerantWriter(sys.stdout)
    sys.stdout = writer  # type: ignore[assignment]
    return writer


def silence_interpreter_flush(writer: PipeTolerantWriter) -> None:
    """Stop CPython's exit-time flush from printing to a pipe that is gone.

    Even with every `write` guarded, the interpreter flushes the real stdout during shutdown
    and prints `Exception ignored in: <_io.TextIOWrapper ...> BrokenPipeError` to stderr. That
    is noise on a command that in fact succeeded, and it looks like a crash. Pointing fd 1 at
    the null device gives the final flush somewhere harmless to go.
    """
    if not writer.closed_by_reader:
        return
    try:
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, sys.__stdout__.fileno())
        os.close(devnull)
    except OSError:
        # Nothing left to salvage, and the command's real work is already done.
        pass
