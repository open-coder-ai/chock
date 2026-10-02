"""Catalog fetching: commit pins resolve to a commit object, git runs isolated from the caller."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

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
        return into, _fetch_commit(source, remote, ref.lower(), into)
    if ref and _SHORT_SHA.fullmatch(ref):
        raise _pin_error(source, ref, "a short hex ref is ambiguous; pin a full 40-character commit SHA")
    if ref:
        _check_ref_syntax(source, ref)
        print(
            f"chock add: warning: {ref!r} is a branch or tag, which can move. Pin a full commit SHA instead.",
            file=sys.stderr,
        )
    return into, _clone_ref(source, remote, ref, into)
