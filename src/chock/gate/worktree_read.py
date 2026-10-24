"""Reading a changed worktree file without following a link or waiting on a pipe.

Extracted into the vendored per-agent runtime beside write_gate, so it is stdlib-only and may not import chock.
"""

from __future__ import annotations

import os

from .stop_reentry import STOP_MODE_DIR, STOP_MODE_FILE, STOP_MODE_MASK

#: st_mode type bits (`stat` is not importable in the vendored runtime): a link is read as git stores it.
_MODE_LINK = 0o120000


def _open_text(target, kind):
    """(text, why) of a link's target or a regular file, opened without following a link or waiting on a pipe."""
    try:
        if kind == _MODE_LINK:
            return os.readlink(target), None
        if kind != STOP_MODE_FILE:
            return None, f"{target} is neither a file nor a link"
        fd = os.open(target, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
        with os.fdopen(fd, "rb") as handle:
            return handle.read().decode("utf-8"), None
    except UnicodeDecodeError:
        return None, None
    except OSError as exc:
        return None, f"{target} could not be read ({exc})"


def worktree_text(target):
    """(text, why): `target` as the worktree holds it, never opening a FIFO, device or the file a link names.

    A file that is gone reads as "" (its path is still judged), a directory or undecodable file as no
    text, a link as the target git stores for it. Anything else is refused with a reason: opening a
    FIFO or device can block the hook until its client's timeout, which a client may read as an allow.
    """
    try:
        kind = os.lstat(target).st_mode & STOP_MODE_MASK
    except FileNotFoundError:
        return "", None
    except OSError as exc:
        return None, f"{target} could not be examined ({exc})"
    return (None, None) if kind == STOP_MODE_DIR else _open_text(target, kind)
