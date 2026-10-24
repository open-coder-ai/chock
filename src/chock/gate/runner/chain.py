"""Gate runner: the decision log's hash chain, each line naming the sha256 of the one before it. Stdlib only."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

# >>> gate.py 23
#: Each line names the sha256 of the line before it (`prev`, its exact bytes without the newline) and its place (`seq`).
LOG_CHAIN_PREV, LOG_CHAIN_SEQ = "prev", "seq"
#: A line written outside the chain names why (`lock`: the lock stayed held; `unreadable`: the last line could not be read).
LOG_CHAIN_UNCHAINED = "unchained"
LOG_CHAIN_KEYS = (LOG_CHAIN_PREV, LOG_CHAIN_SEQ, LOG_CHAIN_UNCHAINED)
#: The `prev` of the first line a log ever had: no line came before it.
LOG_CHAIN_GENESIS = "0" * 64
#: How far back from a log's end its last line is looked for before the whole file is read.
_LOG_TAIL_BYTES = 65_536

#: `st_mode`'s file-type bits and the two types a log's files and directories may be (`stat.S_IFMT`, `S_IFREG`, `S_IFDIR`).
LOG_MODE_MASK, LOG_MODE_FILE, LOG_MODE_DIR = 0o170000, 0o100000, 0o040000
LOG_UNSAFE = "not a regular file in real directories; refusing to open it"
#: Opening a log never follows a symlink and never waits on a FIFO.
LOG_OPEN_FLAGS = getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)


def log_rotated(path):
    """Where `log_append` moves a full log: `<stem>.1<suffix>` beside it."""
    path = Path(path)
    return path.with_name(path.stem + ".1" + path.suffix)


def log_tail(path):
    """(the last line of `path` as bytes without its newline or None, whether the file ends without a newline)."""
    try:
        with open(path, "rb") as fh:
            size = fh.seek(0, os.SEEK_END)
            fh.seek(max(0, size - _LOG_TAIL_BYTES))
            tail = fh.read()
            if b"\n" not in tail.rstrip(b"\n") and size > len(tail):
                fh.seek(0)
                tail = fh.read()  # one line longer than the tail read: read the whole file
    except FileNotFoundError:
        return None, False
    last = tail.rstrip(b"\n").rsplit(b"\n", 1)[-1]
    return last or None, bool(tail) and not tail.endswith(b"\n")


def log_last_line(path):
    """The last line of `path` as bytes, without its newline; None for a missing or empty file."""
    return log_tail(path)[0]


def log_line_hash(line):
    """The chain's link to a line: the sha256 of its exact bytes, without the newline."""
    return hashlib.sha256(line).hexdigest()


def log_line_seq(line):
    """A line's place in its chain, or -1 when it carries none (an unchained or unreadable line)."""
    try:
        seq = json.loads(line).get(LOG_CHAIN_SEQ)
    except (ValueError, AttributeError):
        return -1
    return seq if type(seq) is int else -1


def log_chain_after(last):
    """The chain fields of the line after `last` (bytes); the genesis when no line came before."""
    if last is None:
        return {LOG_CHAIN_SEQ: 0, LOG_CHAIN_PREV: LOG_CHAIN_GENESIS}
    return {LOG_CHAIN_SEQ: log_line_seq(last) + 1, LOG_CHAIN_PREV: log_line_hash(last)}


def log_path_safe(path):
    """Whether the log, its lock and rotated file are regular files or absent, and its two directories real directories.

    lstat, so a symlink, FIFO, socket or device is refused before anything opens it: opening a FIFO blocks the hook
    until its timeout, which a client may read as an allow.
    """
    path = Path(path)
    checks = (
        (path, LOG_MODE_FILE),
        (Path(str(path) + ".lock"), LOG_MODE_FILE),
        (log_rotated(path), LOG_MODE_FILE),
        (path.parent, LOG_MODE_DIR),
        (path.parent.parent, LOG_MODE_DIR),
    )
    for target, kind in checks:
        try:
            mode = os.lstat(target).st_mode
        except FileNotFoundError:
            continue
        except OSError:
            return False
        if mode & LOG_MODE_MASK != kind:
            return False
    return True


def log_require_safe(path):
    """Raise OSError unless `log_path_safe(path)`."""
    if not log_path_safe(path):
        raise OSError(LOG_UNSAFE)
