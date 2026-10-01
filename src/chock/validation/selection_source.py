"""A selection file's text at a git revision or in the worktree; anything but a regular file is an error."""

from __future__ import annotations

import stat
import subprocess
from pathlib import Path

from chock.validation.selection_baseline import Kind, SelectionInvalidError

_TREE, _REGULAR = "040000", frozenset({"100644", "100755"})
_MODES = {"120000": "a symlink", "040000": "a directory", "160000": "a submodule"}


def _git(repo_root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(  # noqa: S603 -- reading a git revision is this check's whole job
        ["git", "-C", str(repo_root), *args],  # noqa: S607 -- git from PATH
        capture_output=True,
        text=True,
        check=False,
    )


def _mode_at(repo_root: Path, ref: str, path: Path) -> str | None:
    """The git mode of `path` at `ref`; None when the revision has nothing there."""
    result = _git(repo_root, "ls-tree", ref, "--", path.as_posix())
    if result.returncode != 0:
        msg = f"cannot list {path} at {ref}: {result.stderr.strip()}"
        raise SelectionInvalidError(msg)
    return result.stdout.split(maxsplit=1)[0] if result.stdout.strip() else None


def _at_ref(repo_root: Path, kind: Kind, ref: str) -> str | None:
    rel = Path(kind.filename)
    for part, want in ((rel.parent, "a directory"), (rel, "a regular file")):
        mode = _mode_at(repo_root, ref, part)
        if mode is None:
            return None
        if mode != _TREE if part == rel.parent else mode not in _REGULAR:
            what = "a file" if mode in _REGULAR else _MODES.get(mode, f"object mode {mode}")
            msg = f"{part} is {what} at {ref}, not {want}; the base selection cannot be trusted as a baseline"
            raise SelectionInvalidError(msg)
    result = _git(repo_root, "show", f"{ref}:{kind.filename}")
    if result.returncode != 0:
        msg = f"cannot read {kind.filename} at {ref}: {result.stderr.strip()}"
        raise SelectionInvalidError(msg)
    return result.stdout


def _in_worktree(repo_root: Path, kind: Kind) -> str | None:
    """The worktree's selection; None only when nothing is at its path. A link or non-file is an error."""
    rel = Path(kind.filename)
    for part in (*reversed(rel.parents[:-1]), rel):
        try:
            mode = (repo_root / part).lstat().st_mode
        except FileNotFoundError:
            return None
        if stat.S_ISLNK(mode) or (part == rel and not stat.S_ISREG(mode)):
            msg = f"{part} is a symlink or not a regular file; a selection must be a committed regular file"
            raise SelectionInvalidError(msg)
        if part != rel and not stat.S_ISDIR(mode):
            msg = f"{part} is a file, not a directory; the runtime finds no selection under it and falls back"
            raise SelectionInvalidError(msg)
    return (repo_root / rel).read_text(encoding="utf-8")


def selection_text(repo_root: Path, kind: Kind, ref: str | None) -> str | None:
    """A selection file at `ref` (None: the worktree); None when that revision carried none."""
    return _in_worktree(repo_root, kind) if ref is None else _at_ref(repo_root, kind, ref)
