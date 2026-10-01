"""Read-only git plumbing for the history scan: commits, the blobs they introduced, blob bytes.

List argv only, no shell. Nothing here checks out, rewrites or runs a repo hook: `log --raw` and
`cat-file` read the object database. Textconv, external diff, signature verification and filters
are never applied, and any git failure is an error (never an empty answer).
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path

_GIT = shutil.which("git") or "git"
# Command-line config beats repo config: a repo may name a gpg/ssh program or ask for signature checks.
_BASE = (
    _GIT,
    "--no-optional-locks",
    "-c", "core.quotePath=false",
    "-c", "log.showSignature=false",
    "-c", "gpg.program=false",
    "-c", "gpg.ssh.program=false",
    "-c", "gpg.x509.program=false",
)  # fmt: skip
_DROPPED_ENV = ("GIT_EXTERNAL_DIFF", "GIT_PAGER", "GIT_ASKPASS", "GIT_SSH", "GIT_SSH_COMMAND")
_OID_RE = re.compile(r"^[0-9a-f]{40,64}$")
_COMMIT_MARK = b"\x01"
_SUBMODULE = "160000"
_RENAME_STATUS = ("R", "C")
_BATCH_BYTES = 8 * 1024 * 1024
_BATCH_MAX = 500
_READ = 65536
_BINARY_PROBE = 8000
_CHECK_FIELDS = 3  # "<oid> <type> <size>"
_NO_MATCH_RC = 1


class HistoryError(Exception):
    """A scan that cannot run or cannot decide; the caller fails closed."""


@dataclass(frozen=True)
class Touch:
    """One commit introducing `oid` at `path`."""

    commit: str
    path: str
    oid: str


@dataclass
class Log:
    touches: list[Touch] = field(default_factory=list)
    submodules: int = 0


def _env() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if k not in _DROPPED_ENV}


def _spawn(repo: Path, args: Sequence[str], stdin: int | None, stderr: object) -> subprocess.Popen[bytes]:
    try:
        return subprocess.Popen(  # noqa: S603 -- fixed git binary, list argv, read-only subcommands
            [*_BASE, *args], cwd=str(repo), env=_env(), stdin=stdin, stdout=subprocess.PIPE, stderr=stderr
        )
    except OSError as exc:
        raise HistoryError(f"cannot run git: {exc}") from exc


def _run(repo: Path, args: Sequence[str], data: bytes | None = None) -> tuple[int, bytes, str]:
    try:
        proc = subprocess.run(  # noqa: S603 -- fixed git binary, list argv, read-only subcommands
            [*_BASE, *args], cwd=str(repo), env=_env(), input=data, capture_output=True, check=False
        )
    except OSError as exc:
        raise HistoryError(f"cannot run git: {exc}") from exc
    return proc.returncode, proc.stdout, proc.stderr.decode("utf-8", "replace").strip()[:300]


def _git(repo: Path, args: Sequence[str], data: bytes | None = None) -> bytes:
    code, out, err = _run(repo, args, data)
    if code != 0:
        raise HistoryError(f"git {args[0]} failed: {err}")
    return out


def require_repo(repo: Path) -> None:
    """Refuse anything that is not a git repository git itself can open."""
    if not repo.is_dir():
        raise HistoryError(f"{str(repo)!r} is not a directory")
    _git(repo, ["rev-parse", "--git-dir"])


def resolve_rev(repo: Path, rev: str) -> str | None:
    """The commit id `rev` names; None when git says it names no commit. An option-like ref is refused."""
    if not rev or rev.startswith("-") or "\0" in rev or "\n" in rev:
        raise HistoryError(f"refusing ref {rev!r}: a ref may not start with '-' or hold control characters")
    code, out, err = _run(repo, ["rev-parse", "--verify", "--quiet", "--end-of-options", f"{rev}^{{commit}}"])
    if code == 0 and _OID_RE.match(out.decode().strip()):
        return out.decode().strip()
    if code in (0, _NO_MATCH_RC) and not err:
        return None
    raise HistoryError(f"git rev-parse failed: {err}")


def is_shallow(repo: Path) -> bool:
    return _git(repo, ["rev-parse", "--is-shallow-repository"]).decode().strip() == "true"


def _range(since: str | None) -> list[str]:
    return [f"{since}..HEAD"] if since else ["HEAD"]


def count_commits(repo: Path, since: str | None) -> int:
    return int(_git(repo, ["rev-list", "--count", *_range(since), "--"]).decode().strip() or 0)


def _stream_tokens(proc: subprocess.Popen[bytes]) -> Iterator[bytes]:
    """NUL-separated tokens of `proc.stdout`, read in chunks so a long history is never held whole."""
    rest = b""
    assert proc.stdout is not None  # noqa: S101 -- stdout=PIPE above
    while chunk := proc.stdout.read(_READ):
        parts = (rest + chunk).split(b"\0")
        rest = parts.pop()
        yield from parts
    if rest:
        yield rest


def _records(tokens: Iterator[bytes], log: Log) -> Iterator[tuple[str, str, str]]:
    """(commit, new oid, new path) per raw entry of `log -z --raw`; a merge is judged against each parent."""
    commit = ""
    for raw in tokens:
        if raw.startswith(_COMMIT_MARK):
            commit = raw[1:].decode()
            continue
        meta = raw.lstrip(b"\n").decode("utf-8", "replace")
        if not meta.startswith(":"):
            continue
        fields = meta[1:].split(" ")
        path = os.fsdecode(next(tokens, b""))
        if fields[-1].startswith(_RENAME_STATUS):
            path = os.fsdecode(next(tokens, b""))
        if fields[1] == _SUBMODULE:
            log.submodules += 1
        else:
            yield commit, fields[3], path


def touches(repo: Path, since: str | None, max_commits: int) -> Log:
    """Blobs added or changed per commit, oldest commit first (the newest `max_commits` of the range)."""
    args = [
        "log", "-z", "--raw", "-m", "-M", "--topo-order", "--reverse", "--no-abbrev",
        "--no-ext-diff", "--no-textconv", "--no-show-signature", "--diff-filter=ACMRT",
        "-n", str(max_commits), "--format=%x01%H", *_range(since), "--",
    ]  # fmt: skip
    result = Log()
    seen: set[Touch] = set()
    with tempfile.TemporaryFile() as err:
        proc = _spawn(repo, args, None, err)
        for commit, oid, path in _records(_stream_tokens(proc), result):
            item = Touch(commit, path, oid)
            if _OID_RE.match(oid) and item not in seen:
                seen.add(item)
                result.touches.append(item)
        code = proc.wait()
        err.seek(0)
        detail = err.read().decode("utf-8", "replace").strip()[:300]
    if code != 0:
        raise HistoryError(f"git log failed: {detail}")
    return result


def blob_sizes(repo: Path, oids: Sequence[str]) -> dict[str, int]:
    """Size of each blob object; an oid git cannot find is left out for the caller to refuse."""
    sizes: dict[str, int] = {}
    for start in range(0, len(oids), _BATCH_MAX):
        chunk = oids[start : start + _BATCH_MAX]
        out = _git(repo, ["cat-file", "--batch-check"], ("\n".join(chunk) + "\n").encode())
        for line in out.decode().splitlines():
            parts = line.split(" ")
            if len(parts) == _CHECK_FIELDS and parts[1] == "blob":
                sizes[parts[0]] = int(parts[2])
    return sizes


def _batches(oids: Sequence[str], sizes: dict[str, int]) -> Iterator[list[str]]:
    """Groups of oids whose bytes together stay under the batch cap."""
    group: list[str] = []
    total = 0
    for oid in oids:
        if group and (total + sizes[oid] > _BATCH_BYTES or len(group) >= _BATCH_MAX):
            yield group
            group, total = [], 0
        group.append(oid)
        total += sizes[oid]
    if group:
        yield group


def read_blobs(repo: Path, oids: Sequence[str], sizes: dict[str, int]) -> Iterator[tuple[str, bytes]]:
    """(oid, bytes) for each blob through `cat-file --batch`; a missing or short blob is an error."""
    for group in _batches(oids, sizes):
        out = _git(repo, ["cat-file", "--batch"], ("\n".join(group) + "\n").encode())
        pos = 0
        for oid in group:
            end = out.find(b"\n", pos)
            header = out[pos:end].decode().split(" ") if end >= 0 else []
            if len(header) != _CHECK_FIELDS or header[0] != oid or header[1] != "blob":
                raise HistoryError(f"blob {oid} is missing or unreadable in the object database")
            size = int(header[2])
            body = out[end + 1 : end + 1 + size]
            if len(body) != size:
                raise HistoryError(f"blob {oid} is truncated in the object database")
            yield oid, body
            pos = end + 1 + size + 1


def is_binary(data: bytes) -> bool:
    return b"\0" in data[:_BINARY_PROBE]
