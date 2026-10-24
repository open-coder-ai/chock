"""Catalog fetching: commit pins resolve to a commit object, git runs isolated from the caller."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from importlib import metadata
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import chock

REMOTE_TIMEOUT = 600
LOCAL_TIMEOUT = 60
ALLOWED_PROTOCOLS = "https:ssh:file:git"
#: Hooks off, fsmonitor off, and line endings as committed: a checkout under `core.autocrlf=true`
#: (Windows' usual setting) would hash differently from the same commit on Linux.
INERT = (
    "-c",
    "core.hooksPath=/dev/null",
    "-c",
    "core.fsmonitor=false",
    "-c",
    "core.autocrlf=false",
    "-c",
    "core.eol=lf",
)
_TEXT_PROBE = 8000  # git's own binary heuristic: a NUL in the first 8000 bytes
_VCS_DIR = ".git"

_DROPPED_ENV = frozenset(
    {
        "GIT_DIR",
        "GIT_WORK_TREE",
        "GIT_INDEX_FILE",
        "GIT_OBJECT_DIRECTORY",
        "GIT_ALTERNATE_OBJECT_DIRECTORIES",
        "GIT_COMMON_DIR",
        "GIT_NAMESPACE",
        "GIT_CEILING_DIRECTORIES",
        "GIT_CONFIG",
        "GIT_CONFIG_PARAMETERS",
        "GIT_CONFIG_COUNT",
        "GIT_EXEC_PATH",
        "GIT_TEMPLATE_DIR",
    }
)
_DROPPED_PREFIXES = ("GIT_CONFIG_KEY_", "GIT_CONFIG_VALUE_")

PUBLISHED = "refs/chock-published"
_PUBLISHED_REFSPECS = (f"+refs/heads/*:{PUBLISHED}/heads/*", f"+refs/tags/*:{PUBLISHED}/tags/*")

_FULL_SHA = re.compile(r"[0-9a-fA-F]{40}")
_SHORT_SHA = re.compile(r"[0-9a-fA-F]{7,39}")
_SAFE_REF = re.compile(r"[A-Za-z0-9._/+-]+")


class PinError(RuntimeError):
    """A catalog ref was refused: not a commit the remote can prove."""


def git_env() -> dict[str, str]:
    """The caller's environment minus anything that redirects git; ssh, proxy and CA settings stay."""
    env = {k: v for k, v in os.environ.items() if k not in _DROPPED_ENV and not k.startswith(_DROPPED_PREFIXES)}
    env["GIT_ALLOW_PROTOCOL"] = ALLOWED_PROTOCOLS
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    env["GIT_TERMINAL_PROMPT"] = "0"
    return env


def _run(args: list[str], timeout: int = LOCAL_TIMEOUT) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(  # noqa: S603 -- running git to fetch the requested catalog is this command's job
            args,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            env=git_env(),
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        msg = f"git {args[1] if len(args) > 1 else ''} timed out after {timeout}s"
        raise RuntimeError(msg) from exc


def _in(into: Path, *args: str) -> list[str]:
    """A git command bound to the temp repo at `into`, whatever the surrounding environment says."""
    return ["git", f"--git-dir={into / '.git'}", f"--work-tree={into}", *INERT, *args]


def redact_source(source: str) -> str:
    """The source without the userinfo of a URL: a token typed into `--from` is never stored or printed."""
    if not is_remote_source(source):
        return source
    parts = urlsplit(source)
    if "@" not in parts.netloc or not parts.scheme:
        return source
    return urlunsplit(parts._replace(netloc=parts.netloc.rpartition("@")[2]))


def _scrub(text: str, source: str) -> str:
    return text.replace(source, redact_source(source))


def _pin_error(source: str, ref: str, why: str) -> PinError:
    return PinError(f"chock add: refusing catalog {redact_source(source)} at {ref!r}: {why} (nothing installed)")


def _check_ref_syntax(source: str, ref: str) -> None:
    """A ref is never an option and never outside git's ref rules."""
    if ref.startswith("-") or not _SAFE_REF.fullmatch(ref):
        raise _pin_error(source, ref, "not a valid git ref name")
    if _run(["git", "check-ref-format", "--allow-onelevel", ref]).returncode != 0:
        raise _pin_error(source, ref, "not a valid git ref name")


def _fetch_commit(source: str, remote: str, sha: str, into: Path) -> str:
    """Fetch exactly the commit object `sha` and prove HEAD is it before any file is read."""
    into.mkdir(parents=True, exist_ok=True)
    steps = (
        (["git", "init", "--quiet", "--template=", str(into)], LOCAL_TIMEOUT),
        (_in(into, "fetch", "--quiet", "--depth", "1", "--", remote, sha), REMOTE_TIMEOUT),
        (_in(into, "rev-parse", "--verify", "--quiet", f"{sha}^{{commit}}"), LOCAL_TIMEOUT),
        (_in(into, "checkout", "--quiet", "--detach", sha), LOCAL_TIMEOUT),
    )
    for args, timeout in steps:
        try:
            result = _run(args, timeout)
        except RuntimeError as exc:
            raise _pin_error(source, sha, str(exc)) from exc
        if result.returncode != 0:
            detail = _scrub(result.stderr.strip(), source) or "git step failed"
            raise _pin_error(source, sha, f"commit not available from the remote by id ({detail})")
    head = _run(_in(into, "rev-parse", "HEAD"))
    if head.returncode != 0 or head.stdout.strip().lower() != sha:
        raise _pin_error(source, sha, "the checked-out commit is not the pinned commit")
    return sha


def _require_published(source: str, remote: str, sha: str, into: Path) -> None:
    """Refuse a commit that is on no branch or tag the remote publishes (a fork's or a pull request's)."""
    try:
        fetched = _run(
            _in(into, "fetch", "--quiet", "--filter=blob:none", "--", remote, *_PUBLISHED_REFSPECS), REMOTE_TIMEOUT
        )
        if fetched.returncode != 0:
            detail = fetched.stderr.strip() or "git step failed"
            raise _pin_error(source, sha, f"could not list the branches and tags the source publishes ({detail})")
        found = _run(_in(into, "for-each-ref", "--count=1", f"--contains={sha}", "--format=%(refname)", PUBLISHED))
    except RuntimeError as exc:
        raise _pin_error(source, sha, str(exc)) from exc
    if found.returncode != 0 or not found.stdout.strip():
        why = f"commit {sha} is not on any branch or tag of {redact_source(source)}; a fork's or a pull request's commit is refused"
        raise _pin_error(source, sha, why)


def _clone_ref(source: str, remote: str, ref: str | None, into: Path) -> str | None:
    args = ["git", *INERT, "clone", "--quiet", "--depth", "1", "--template="]
    if ref:
        args += ["--branch", ref]
    result = _run([*args, "--", remote, str(into)], REMOTE_TIMEOUT)
    if result.returncode != 0:
        msg = (
            f"could not fetch catalog {redact_source(source)}"
            + (f" at {ref}" if ref else "")
            + f":\n{_scrub(result.stderr.strip(), source)}"
        )
        raise RuntimeError(msg)
    resolved = _run(_in(into, "rev-parse", "HEAD"))
    return (resolved.stdout.strip() or None) if resolved.returncode == 0 else None


def _committed_tree(local: Path) -> tuple[Path, str] | None:
    """(toplevel, prefix) when `local` is a directory that HEAD of its checkout holds, else None."""
    try:
        found = _run(["git", "-C", str(local), *INERT, "rev-parse", "--show-toplevel", "--show-prefix", "HEAD"])
    except (OSError, RuntimeError):
        return None
    lines = found.stdout.splitlines() if found.returncode == 0 else []
    if len(lines) != 3:  # noqa: PLR2004 -- one line per flag, then the commit
        return None
    toplevel, prefix, _head = lines
    tracked = _run(["git", "-C", str(local), *INERT, "rev-parse", "--verify", "--quiet", f"HEAD:{prefix}"])
    if tracked.returncode != 0:
        return None
    return Path(toplevel), prefix


def _is_text(data: bytes) -> bool:
    return b"\0" not in data[:_TEXT_PROBE]


def _copy_normalised(local: Path, into: Path) -> None:
    """Copy a plain directory, text files to LF: the bytes git would commit, so a later clone verifies.

    Symlinks are copied as links, never followed (`os.walk` stays inside `into`): the pack check refuses
    them later, and nothing outside the copy is read or rewritten.
    """
    shutil.copytree(local, into, symlinks=True, ignore=shutil.ignore_patterns(_VCS_DIR))
    for parent, _dirs, files in os.walk(into):
        for path in (Path(parent, name) for name in files):
            if path.is_symlink():
                continue
            data = path.read_bytes()
            if b"\r\n" in data and _is_text(data):
                path.write_bytes(data.replace(b"\r\n", b"\n"))


def _snapshot_local(source: str, local: Path, into: Path) -> tuple[Path, str | None]:
    """A local source with no ref: a clone of its checkout at HEAD, or the directory as git would commit it."""
    committed = _committed_tree(local)
    if committed is None:
        _copy_normalised(local, into)
        return into, None
    toplevel, prefix = committed
    head = _clone_ref(source, toplevel.as_uri(), None, into)
    return into / prefix, head


_REMOTE_FORM = re.compile(r"^(?:[A-Za-z][A-Za-z0-9+.-]*://|[^/\\:@\s]+@[^/\\:\s]+:)")


def is_remote_source(source: str) -> bool:
    """True when the text is spelled as a URL or scp-style address: never read from disk, whatever exists there."""
    return bool(_REMOTE_FORM.match(source))


def local_source(source: str) -> Path | None:
    """The existing local path a source names, or None for a remote spelling or a path that is not there."""
    if is_remote_source(source):
        return None
    path = Path(source).expanduser()
    return path if path.exists() else None


def fetch_catalog(source: str, ref: str | None, into: Path) -> tuple[Path, str | None]:
    """Make the catalog available locally. Returns (root, resolved commit or None).

    The returned tree holds the bytes a clone of the catalog holds: a local checkout is cloned at its
    HEAD (uncommitted edits are left out), a plain directory is copied with its text files normalised to LF.
    """
    local = local_source(source)
    if local is not None and local.is_dir() and not ref:
        return _snapshot_local(source, local.resolve(), into)
    remote = str(local.resolve()) if local is not None else source

    if ref and _FULL_SHA.fullmatch(ref):
        sha = _fetch_commit(source, remote, ref.lower(), into)
        if local is None:
            _require_published(source, remote, sha, into)
        return into, sha
    if ref and _SHORT_SHA.fullmatch(ref):
        raise _pin_error(source, ref, "a short hex ref is ambiguous; pin a full 40-character commit SHA")
    if ref:
        _check_ref_syntax(source, ref)
        print(
            f"chock add: warning: {ref!r} is a branch or tag, which can move. Pin a full commit SHA instead.",
            file=sys.stderr,
        )
    return into, _clone_ref(source, remote, ref, into)


def engine_commit() -> str | None:
    """The commit this chock was installed from (a VCS install) or runs from (a source checkout), else None."""
    try:
        direct = json.loads(metadata.distribution("chock").read_text("direct_url.json") or "{}")
    except (metadata.PackageNotFoundError, ValueError):
        direct = {}
    commit = (direct.get("vcs_info") or {}).get("commit_id") if isinstance(direct, dict) else None
    if commit:
        return str(commit)
    source = Path(chock.__file__).resolve().parents[2]
    if not (source / ".git").exists():
        return None
    try:
        done = _run(["git", *INERT, "-C", str(source), "rev-parse", "HEAD"])
    except OSError:
        return None
    if done.returncode != 0:
        return None
    return done.stdout.strip() or None
