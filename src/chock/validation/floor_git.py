"""Read-only git access for `chock check --floor`: committed files by revision, never the working tree."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

_GIT_TIMEOUT = 120
_TREE_FIELDS = 2
_BLOB = "blob"
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
            self._entries = found
        return self._entries

    def paths(self, prefix: str = "") -> list[str]:
        return sorted(path for path in self.entries() if path.startswith(prefix))

    def has(self, path: str) -> bool:
        return path in self.entries()

    def oid(self, path: str) -> str | None:
        entry = self.entries().get(path)
        return entry[1] if entry else None

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


def merge_base(repo: Path, base: str, head: str) -> str:
    proc = git(repo, "merge-base", base, head)
    sha = proc.stdout.decode("ascii", "replace").strip()
    if proc.returncode or not sha:
        msg = f"base {base[:12]} and head {head[:12]} share no history; refusing to judge an unrelated range"
        raise FloorError(msg)
    return sha
