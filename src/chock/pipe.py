"""Keep a closed stdout from abandoning a command halfway through."""

from __future__ import annotations

import errno
import os
import sys
from typing import Any, TextIO


def _is_broken_pipe(exc: OSError) -> bool:
    return isinstance(exc, BrokenPipeError) or exc.errno in (errno.EPIPE, errno.EINVAL)


class PipeTolerantWriter:
    """Wrap a text stream so a vanished reader stops output rather than the program."""

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
    """Stop CPython's exit-time flush from printing to a pipe that is gone."""
    if not writer.closed_by_reader:
        return
    try:
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, sys.__stdout__.fileno())
        os.close(devnull)
    except OSError:
        pass
