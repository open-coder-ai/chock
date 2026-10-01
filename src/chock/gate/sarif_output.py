"""Where `--format sarif --output` may write: a plain file, never through a symlink the repo can plant."""

from __future__ import annotations

import os
import stat
import tempfile
from pathlib import Path


def _prefixes(path: Path) -> list[Path]:
    """Every prefix of the absolute `path`, root first, with no `..` resolved away."""
    parts = (path if path.is_absolute() else Path.cwd() / path).parts
    return [Path(*parts[: i + 1]) for i in range(len(parts))]


def refusal(path: Path, repo: Path) -> str | None:
    """Why `path` is no place to write, or None: a `..`, a symlink (the target, or any part below the repo),
    a missing directory, or an existing target that is not a regular file."""
    if ".." in path.parts:
        return f"{path} has a `..` component"
    roots = {Path(os.path.abspath(repo)), repo.resolve()}
    prefixes = _prefixes(path)
    for prefix in prefixes:
        below = any(prefix != root and prefix.is_relative_to(root) for root in roots)
        if prefix.is_symlink() and (below or prefix == prefixes[-1]):
            return f"{prefix} is a symlink"
    if not path.parent.is_dir():
        return f"{path.parent} is not a directory"
    try:
        mode = os.lstat(path).st_mode
    except FileNotFoundError:
        return None
    return None if stat.S_ISREG(mode) else f"{path} exists and is not a regular file"


def write_output(path: Path, text: str, repo: Path) -> str | None:
    """Write `text` to `path` through a new file beside it (mkstemp: O_EXCL, no symlink followed) and rename it
    into place; None on success, else why not. The target is checked again just before the rename."""
    if reason := refusal(path, repo):
        return reason
    try:
        fd, temp = tempfile.mkstemp(prefix=".chock-sarif-", dir=path.parent)
    except OSError as exc:
        return str(exc)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        if reason := refusal(path, repo):
            return reason
        os.replace(temp, path)
    except OSError as exc:
        return str(exc)
    finally:
        Path(temp).unlink(missing_ok=True)
    return None
