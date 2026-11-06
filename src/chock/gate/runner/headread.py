"""Gate runner: what `git show HEAD:<path>` prints, read once per process."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

# >>> gate.py 24
_HEAD_GIT = shutil.which("git") or "git"

#: Per process: HEAD resolved once per repo root, and each `git show HEAD:<spec>` run once per (root, HEAD, spec).
#: A failure is stored as None and read back as the same failure.
_HEAD_SHA: dict[str, str | None] = {}
_HEAD_SHOWN: dict[tuple[str, str | None, str], bytes | None] = {}


def _head_sha(root: str) -> str | None:
    if root not in _HEAD_SHA:
        try:
            proc = subprocess.run(  # noqa: S603 -- resolving HEAD once is this cache's key
                [_HEAD_GIT, "-C", root, "rev-parse", "--verify", "--quiet", "HEAD^{commit}"],
                capture_output=True,
                text=True,
                check=False,
                timeout=10,
            )
            sha = proc.stdout.strip() if proc.returncode == 0 else ""
        except (OSError, subprocess.SubprocessError, UnicodeError):
            sha = ""
        _HEAD_SHA[root] = sha or None
    return _HEAD_SHA[root]


def _head_show(repo_root: Path, spec: str) -> bytes | None:
    """The bytes of `git show HEAD:<spec>` run from `repo_root`, read once per process; None when git cannot show it."""
    root = str(repo_root)
    key = (root, _head_sha(root), spec)
    if key not in _HEAD_SHOWN:
        try:
            proc = subprocess.run(  # noqa: S603 -- reading one committed file
                [_HEAD_GIT, "-C", root, "show", f"HEAD:{spec}"],
                capture_output=True,
                check=False,
                timeout=10,
            )
            shown = proc.stdout if proc.returncode == 0 else None
        except (OSError, subprocess.SubprocessError):
            shown = None
        _HEAD_SHOWN[key] = shown
    return _HEAD_SHOWN[key]


def _head_forget() -> None:
    """Drop what was read, for a process that sees HEAD move."""
    _HEAD_SHA.clear()
    _HEAD_SHOWN.clear()


def _text_mode(raw: bytes, errors: str = "strict") -> str:
    """`raw` as a text-mode pipe reads it: utf-8, universal newlines."""
    return raw.decode("utf-8", errors).replace("\r\n", "\n").replace("\r", "\n")
