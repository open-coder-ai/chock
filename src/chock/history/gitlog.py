"""Read-only git plumbing for the history scan: commits, the blobs they introduced, blob bytes.

List argv only, no shell. Nothing here checks out, rewrites or runs a repo hook: `log --raw` and
`cat-file` read the object database. Textconv, external diff and filters are never applied.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path

_GIT = shutil.which("git") or "git"
_BASE = (_GIT, "--no-optional-locks", "-c", "core.quotePath=false")
_OID_RE = re.compile(r"^[0-9a-f]{40,64}$")
_COMMIT_MARK = "\x01"
_SKIP_MODES = frozenset({"160000", "120000"})  # a submodule pointer, a symlink target
_RENAME_STATUS = ("R", "C")
_BATCH = 200
_BINARY_PROBE = 8000
_CHECK_FIELDS = 3  # "<oid> <type> <size>"


class HistoryError(Exception):
    """A scan that cannot run or cannot decide; the caller fails closed."""


@dataclass(frozen=True)
class Touch:
    """One commit introducing `oid` at `path`."""

    commit: str
    path: str
    oid: str


def _git(repo: Path, args: Sequence[str], data: bytes | None = None) -> bytes:
    try:
        proc = subprocess.run(  # noqa: S603 -- fixed git binary, list argv, read-only subcommands
            [*_BASE, *args], cwd=str(repo), input=data, capture_output=True, check=False
        )
    except OSError as exc:
        raise HistoryError(f"cannot run git: {exc}") from exc
    if proc.returncode != 0:
        raise HistoryError(f"git {args[0]} failed: {proc.stderr.decode('utf-8', 'replace').strip()[:300]}")
    return proc.stdout


def resolve_rev(repo: Path, rev: str) -> str:
    """The commit id `rev` names. A ref starting with `-` or naming no commit is refused."""
    if not rev or rev.startswith("-") or "\0" in rev or "\n" in rev:
        raise HistoryError(f"refusing ref {rev!r}: a ref may not start with '-' or hold control characters")
    try:
        out = _git(repo, ["rev-parse", "--verify", "--quiet", "--end-of-options", f"{rev}^{{commit}}"]).decode().strip()
    except HistoryError:
        out = ""
    if not _OID_RE.match(out):
        raise HistoryError(f"{rev!r} does not name a commit")
    return out


def has_commits(repo: Path) -> bool:
    try:
        resolve_rev(repo, "HEAD")
    except HistoryError:
        return False
    return True


def is_shallow(repo: Path) -> bool:
    return _git(repo, ["rev-parse", "--is-shallow-repository"]).decode().strip() == "true"


def _range(since: str | None) -> list[str]:
    return [f"{since}..HEAD"] if since else ["HEAD"]


def count_commits(repo: Path, since: str | None) -> int:
    return int(_git(repo, ["rev-list", "--count", *_range(since), "--"]).decode().strip() or 0)


def _records(raw: bytes) -> Iterator[tuple[str, str, str]]:
    """(commit, new oid, new path) per raw entry of `log -z --raw`; a merge is judged against each parent."""
    tokens = iter(raw.decode("utf-8", "replace").split("\0"))
    commit = ""
    for token in tokens:
        if token.startswith(_COMMIT_MARK):
            commit = token[1:]
            continue
        meta = token.lstrip("\n")
        if not meta.startswith(":"):
            continue
        fields = meta[1:].split(" ")
        path = next(tokens, "")
        if fields[-1].startswith(_RENAME_STATUS):
            path = next(tokens, "")
        if fields[1] not in _SKIP_MODES:
            yield commit, fields[3], path


def touches(repo: Path, since: str | None, max_commits: int) -> list[Touch]:
    """Blobs added or changed per commit, oldest commit first (the newest `max_commits` of the range)."""
    args = [
        "log", "-z", "--raw", "-m", "-M", "--topo-order", "--reverse", "--no-abbrev",
        "--no-ext-diff", "--no-textconv", "--diff-filter=ACMR", "-n", str(max_commits),
        f"--format={_COMMIT_MARK}%H", *_range(since), "--",
    ]  # fmt: skip
    seen: set[Touch] = set()
    out: list[Touch] = []
    for commit, oid, path in _records(_git(repo, args)):
        item = Touch(commit, path, oid)
        if _OID_RE.match(oid) and item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _chunks(items: Sequence[str]) -> Iterator[Sequence[str]]:
    for start in range(0, len(items), _BATCH):
        yield items[start : start + _BATCH]


def blob_sizes(repo: Path, oids: Sequence[str]) -> dict[str, int]:
    """Size of each blob object (missing objects are left out)."""
    sizes: dict[str, int] = {}
    for chunk in _chunks(oids):
        out = _git(repo, ["cat-file", "--batch-check"], ("\n".join(chunk) + "\n").encode())
        for line in out.decode().splitlines():
            parts = line.split(" ")
            if len(parts) == _CHECK_FIELDS and parts[1] == "blob":
                sizes[parts[0]] = int(parts[2])
    return sizes


def read_blobs(repo: Path, oids: Sequence[str]) -> Iterator[tuple[str, bytes]]:
    """(oid, bytes) for each blob, read through `cat-file --batch` in bounded batches."""
    for chunk in _chunks(oids):
        out = _git(repo, ["cat-file", "--batch"], ("\n".join(chunk) + "\n").encode())
        pos = 0
        while pos < len(out):
            end = out.index(b"\n", pos)
            header = out[pos:end].decode().split(" ")
            pos = end + 1
            if len(header) != _CHECK_FIELDS:
                continue
            size = int(header[2])
            yield header[0], out[pos : pos + size]
            pos += size + 1


def is_binary(data: bytes) -> bool:
    return b"\0" in data[:_BINARY_PROBE]
