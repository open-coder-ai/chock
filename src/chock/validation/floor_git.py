"""Read-only git access for `chock check --floor`: committed files by revision, never the working tree."""

from __future__ import annotations

import contextlib
import os
import subprocess
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

_GIT_TIMEOUT = 120
_ATTR_SOURCE = "GIT_ATTR_SOURCE"
_ATTR_GIT = "2.42"
_NO_SUCH_TREE = "chock-floor-no-such-tree"
_TREE_FIELDS = 2
_BLOB, _COMMIT, _GITLINK = "blob", "commit", "160000"
_ABSENT = "000000"
_REGULAR_MODES = ("100644", "100755")


class FloorError(RuntimeError):
    """The floor cannot reach a verdict: exit 2, never a pass."""


def git(repo: Path, *args: str, data: bytes | None = None) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(  # noqa: S603 -- reading committed revisions is this module's whole job
            ["git", "-C", str(repo), "--literal-pathspecs", *args],  # noqa: S607
            input=data,
            capture_output=True,
            check=False,
            timeout=_GIT_TIMEOUT,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        msg = f"git could not run ({type(exc).__name__})"
        raise FloorError(msg) from exc


def toplevel(repo: Path) -> Path:
    """The repository's top level, so a `--repo` below it sees every path; FloorError when `repo` is in none."""
    proc = git(repo.resolve(), "rev-parse", "--show-toplevel")
    top = os.fsdecode(proc.stdout).strip()
    if proc.returncode or not top:
        msg = f"{repo} is not inside a git repository"
        raise FloorError(msg)
    return Path(top).resolve()


def resolve(repo: Path, rev: str, what: str) -> str:
    """The commit `rev` names; FloorError when it names none."""
    proc = git(repo, "rev-parse", "--verify", "--quiet", f"{rev}^{{commit}}")
    sha = proc.stdout.decode("ascii", "replace").strip()
    if proc.returncode or not sha:
        msg = f"{what} ref {rev!r} does not resolve -- refusing to judge an empty range. Fetch it (fetch-depth: 0)."
        raise FloorError(msg)
    return sha


@dataclass
class Revision:
    """One commit's tree, read through git: path listing and file text, each read once."""

    repo: Path
    sha: str
    _entries: dict[str, tuple[str, str]] | None = None
    _gitlinks: dict[str, str] = field(default_factory=dict)
    _texts: dict[str, str | None] = field(default_factory=dict)

    def entries(self) -> dict[str, tuple[str, str]]:
        """path -> (mode, blob oid) for every regular file and symlink in the tree."""
        if self._entries is None:
            proc = git(self.repo, "ls-tree", "-r", "-z", "--full-tree", self.sha)
            if proc.returncode:
                msg = f"git ls-tree {self.sha[:12]} failed"
                raise FloorError(msg)
            found: dict[str, tuple[str, str]] = {}
            for record in proc.stdout.split(b"\0"):
                meta, _, raw_path = record.partition(b"\t")
                parts = meta.decode("ascii", "replace").split()
                if len(parts) > _TREE_FIELDS and parts[1] == _BLOB:
                    found[os.fsdecode(raw_path)] = (parts[0], parts[2])
                elif len(parts) > _TREE_FIELDS and parts[1] == _COMMIT:
                    self._gitlinks[os.fsdecode(raw_path)] = parts[2]
            self._entries = found
        return self._entries

    def gitlinks(self) -> dict[str, str]:
        """path -> commit oid for every submodule pointer in the tree."""
        self.entries()
        return self._gitlinks

    def state(self, path: str) -> tuple[str, str] | None:
        """(mode, oid) of `path` here, a submodule pointer included; None when absent."""
        if path in self.gitlinks():
            return _GITLINK, self._gitlinks[path]
        return self.entries().get(path)

    def paths(self, prefix: str = "") -> list[str]:
        return sorted(path for path in self.entries() if path.startswith(prefix))

    def has(self, path: str) -> bool:
        return path in self.entries()

    def blob(self, path: str) -> bytes | None:
        """The file's bytes as committed; None when the tree has no such file."""
        entry = self.entries().get(path)
        if entry is None:
            return None
        proc = git(self.repo, "cat-file", "blob", entry[1])
        if proc.returncode:
            msg = f"git cat-file {path} at {self.sha[:12]} failed"
            raise FloorError(msg)
        return proc.stdout

    def text(self, path: str) -> str | None:
        """The file as committed, decoded as utf-8 with replacement; None when the tree has no such file."""
        if path not in self._texts:
            data = self.blob(path)
            self._texts[path] = None if data is None else data.decode("utf-8", "replace")
        return self._texts[path]

    def materialise(self, prefix: str, into: Path) -> None:
        """Write the regular files under `prefix` into `into` (symlinks are left out: never followed, never made)."""
        for path in self.paths(prefix):
            mode, _ = self.entries()[path]
            if mode not in _REGULAR_MODES or ".." in Path(path).parts:
                continue
            target = into / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(self.blob(path) or b"")


def require_ancestor(repo: Path, base: str, head: str) -> None:
    """FloorError (undecided) unless `base` is an ancestor of `head`: the floor judges what will land, not a branch."""
    proc = git(repo, "merge-base", "--is-ancestor", base, head)
    if proc.returncode:
        msg = (
            f"base {base[:12]} is not an ancestor of head {head[:12]}; pass the pull request's merge result "
            "as --head (refs/pull/<n>/merge, or the merge queue's head)"
        )
        raise FloorError(msg)


def changed_paths(repo: Path, base: str, head: str) -> list[str]:
    """Every path the tree diff base..head adds, changes, deletes or re-modes; renames are a delete and an add."""
    args = ("--no-renames", "--no-ext-diff", "--no-textconv", "--no-relative", "--ignore-submodules=none")
    proc = git(repo, "diff", "--name-only", "-z", *args, base, head, "--")
    if proc.returncode:
        msg = f"git diff {base[:12]} {head[:12]} failed"
        raise FloorError(msg)
    return sorted(os.fsdecode(raw) for raw in proc.stdout.split(b"\0") if raw)


def history_states(repo: Path, base: str, head: str) -> list[tuple[str, tuple[str, str] | None]]:
    """(path, (mode, oid) or None when deleted) for every entry each commit in base..head writes, a merge read
    against each parent, as the history pass reads them."""
    args = ("log", "-z", "--raw", "-m", "--no-renames", "--no-abbrev", "--no-ext-diff", "--no-textconv")
    proc = git(repo, *args, "--format=", f"{base}..{head}", "--")
    if proc.returncode:
        msg = f"git log {base[:12]}..{head[:12]} failed"
        raise FloorError(msg)
    tokens, found = iter(proc.stdout.split(b"\0")), []
    for raw in tokens:
        meta = raw.lstrip(b"\n").decode("ascii", "replace")
        if not meta.startswith(":"):
            continue
        mode, oid = meta[1:].split(" ")[1], meta[1:].split(" ")[3]
        found.append((os.fsdecode(next(tokens, b"")), None if mode == _ABSENT else (mode, oid)))
    return found


@contextlib.contextmanager
def attributes_from(repo: Path, base_ref: str) -> Iterator[None]:
    """Every git the floor runs reads attributes from the base's tree, never the checkout's or the head's;
    FloorError (undecided) when this git ignores `GIT_ATTR_SOURCE`."""
    saved = os.environ.get(_ATTR_SOURCE)
    os.environ[_ATTR_SOURCE] = _NO_SUCH_TREE
    try:
        if git(repo, "-c", "core.fsmonitor=false", "check-attr", "-a", "--", "probe").returncode == 0:
            msg = f"this git ignores {_ATTR_SOURCE}; the floor needs git {_ATTR_GIT} or newer to read attributes from the base"
            raise FloorError(msg)
        os.environ[_ATTR_SOURCE] = resolve(repo, base_ref, "base")
        yield
    finally:
        if saved is None:
            os.environ.pop(_ATTR_SOURCE, None)
        else:
            os.environ[_ATTR_SOURCE] = saved
