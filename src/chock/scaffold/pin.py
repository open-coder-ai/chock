"""Catalog fetching: commit pins resolve to a commit object, git runs isolated from the caller."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from importlib import metadata
from pathlib import Path

import chock

REMOTE_TIMEOUT = 600
LOCAL_TIMEOUT = 60
ALLOWED_PROTOCOLS = "https:ssh:file:git"
INERT = ("-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false")

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


def _pin_error(source: str, ref: str, why: str) -> PinError:
    return PinError(f"chock add: refusing catalog {source} at {ref!r}: {why} (nothing installed)")


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
            detail = result.stderr.strip() or "git step failed"
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
        why = f"commit {sha} is not on any branch or tag of {source}; a fork's or a pull request's commit is refused"
        raise _pin_error(source, sha, why)


def _clone_ref(source: str, remote: str, ref: str | None, into: Path) -> str | None:
    args = ["git", *INERT, "clone", "--quiet", "--depth", "1", "--template="]
    if ref:
        args += ["--branch", ref]
    result = _run([*args, "--", remote, str(into)], REMOTE_TIMEOUT)
    if result.returncode != 0:
        msg = f"could not fetch catalog {source}" + (f" at {ref}" if ref else "") + f":\n{result.stderr.strip()}"
        raise RuntimeError(msg)
    resolved = _run(_in(into, "rev-parse", "HEAD"))
    return (resolved.stdout.strip() or None) if resolved.returncode == 0 else None


def fetch_catalog(source: str, ref: str | None, into: Path) -> tuple[Path, str | None]:
    """Make the catalog available locally. Returns (root, resolved commit or None)."""
    local = Path(source).expanduser()
    if local.exists() and not ref:
        return local.resolve(), None
    remote = str(local.resolve()) if local.exists() else source

    if ref and _FULL_SHA.fullmatch(ref):
        sha = _fetch_commit(source, remote, ref.lower(), into)
        if not local.exists():
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
