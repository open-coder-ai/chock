"""Safe file access for the MCP registration: no link followed, every directory pinned by fd, atomic replace."""

from __future__ import annotations

import contextlib
import errno
import os
import stat
from pathlib import Path

UNTOUCHED = "; chock will not touch it"


class McpConfigError(ValueError):
    """A client's MCP config cannot be merged into safely; nothing was written."""


def _lstat_checked(root: Path, rel: str) -> os.stat_result | None:
    """lstat of `rel` under `root`: None when absent; refuses a symlink anywhere on the way or a non-regular file."""
    cur = root
    parts = Path(rel).parts
    for i, part in enumerate(parts):
        cur = cur / part
        try:
            st = os.lstat(cur)
        except FileNotFoundError:
            return None
        except OSError as exc:
            msg = f"{rel}: cannot be inspected ({exc.strerror}){UNTOUCHED}"
            raise McpConfigError(msg) from exc
        if stat.S_ISLNK(st.st_mode):
            msg = f"{rel}: {part} is a symlink; chock will not write through it"
            raise McpConfigError(msg)
        wanted = stat.S_ISREG if i == len(parts) - 1 else stat.S_ISDIR
        if not wanted(st.st_mode):
            msg = f"{rel}: {part} is not a {'regular file' if i == len(parts) - 1 else 'directory'}{UNTOUCHED}"
            raise McpConfigError(msg)
    return st


def _fd_safe() -> bool:
    """Whether directory-fd calls can pin the path; elsewhere (e.g. Windows) the path-based fallback runs."""
    needed = (os.open, os.mkdir, os.unlink, os.stat, os.rename)
    return all(f in os.supports_dir_fd for f in needed) and hasattr(os, "O_NOFOLLOW") and hasattr(os, "O_DIRECTORY")


def _open_child(cur: int, part: str, *, create: bool) -> int:
    """Open directory `part` of `cur`: lstat first, open O_NOFOLLOW, then require the fd to be that same inode.

    Some kernels follow a symlink despite O_DIRECTORY|O_NOFOLLOW, so the inode comparison is what closes the swap."""
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    try:
        before = os.stat(part, dir_fd=cur, follow_symlinks=False)
    except FileNotFoundError:
        if not create:
            raise
        os.mkdir(part, 0o777, dir_fd=cur)
        before = os.stat(part, dir_fd=cur, follow_symlinks=False)
    if not stat.S_ISDIR(before.st_mode):
        raise NotADirectoryError(errno.ENOTDIR, "not a directory (or a symlink)")
    nxt = os.open(part, flags, dir_fd=cur)
    after = os.fstat(nxt)
    if (after.st_dev, after.st_ino) != (before.st_dev, before.st_ino):
        os.close(nxt)
        raise NotADirectoryError(errno.ENOTDIR, "replaced while it was being opened")
    return nxt


def _open_dir(root: Path, parts: tuple[str, ...], rel: str, *, create: bool) -> int:
    """An fd on `root/parts`, each component opened from the one before so no swap can redirect it."""
    cur = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    part = ""
    try:
        for part in parts:
            nxt = _open_child(cur, part, create=create)
            os.close(cur)
            cur = nxt
    except OSError as exc:
        os.close(cur)
        msg = f"{rel}: {part} is not a plain directory in the repo ({exc.strerror}){UNTOUCHED}"
        raise McpConfigError(msg) from exc
    return cur


def _write_pinned(root: Path, rel: str, payload: bytes, mode: int) -> None:
    parts = Path(rel).parts
    dirfd = _open_dir(root, parts[:-1], rel, create=True)
    tmp = f".{parts[-1]}.chock-{os.urandom(6).hex()}.tmp"
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode, dir_fd=dirfd)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(payload)
            os.rename(tmp, parts[-1], src_dir_fd=dirfd, dst_dir_fd=dirfd)  # POSIX rename replaces atomically
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(tmp, dir_fd=dirfd)
            raise
    finally:
        os.close(dirfd)


def _write_by_path(path: Path, payload: bytes, mode: int) -> None:
    """Fallback where directory fds are unsupported: same temp-file replace, but by path (not swap-proof)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.chock-{os.urandom(6).hex()}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
        tmp.replace(path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def write_file(root: Path, rel: str, payload: bytes, mode: int) -> None:
    """Replace `rel` through a same-directory temp file, every directory pinned by fd against a late swap."""
    _lstat_checked(root, rel)
    if _fd_safe():
        _write_pinned(root, rel, payload, mode)
    else:
        _write_by_path(root / rel, payload, mode)


def remove_file(root: Path, rel: str) -> None:
    _lstat_checked(root, rel)
    if not _fd_safe():
        (root / rel).unlink()
        return
    parts = Path(rel).parts
    dirfd = _open_dir(root, parts[:-1], rel, create=False)
    try:
        os.unlink(parts[-1], dir_fd=dirfd)
    finally:
        os.close(dirfd)
