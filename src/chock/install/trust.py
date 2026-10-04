"""Trust for a selection's catalog: only listed or user-allowed sources, and only commits on their published branch."""

from __future__ import annotations

import shlex
from pathlib import Path

from chock.install import package
from chock.install.resolve import REFUSED
from chock.scaffold.add import IntegrityError
from chock.scaffold.pin import INERT, REMOTE_TIMEOUT, _run


def check_source(source: str, allowed: list[str]) -> None:
    """Refuse a source the data file does not trust and the user did not name on the command line."""
    if source in package.settings()["trusted_sources"] or source in allowed:
        return
    msg = (
        f"catalog source {source!r} is not trusted. A selection cannot widen trust by itself; "
        f"to install from it anyway, pass --allow-source {shlex.quote(source)}. {REFUSED}"
    )
    raise IntegrityError(msg)


def require_on_branch(source: str, sha: str, into: Path) -> None:
    """Refuse `sha` unless it is reachable from the source's published branch (a fork's commit is not)."""
    branch = package.settings()["published_branch"]
    local = Path(source).expanduser()
    remote = str(local.resolve()) if local.exists() else source
    clone = ["git", *INERT, "clone", "--quiet", "--bare", "--filter=blob:none", "--single-branch", "--branch"]
    result = _run([*clone, branch, "--", remote, str(into)], REMOTE_TIMEOUT)
    if result.returncode != 0:
        msg = f"could not read {source}'s {branch} branch ({result.stderr.strip()}). {REFUSED}"
        raise IntegrityError(msg)
    check = _run(["git", f"--git-dir={into}", *INERT, "merge-base", "--is-ancestor", sha, branch])
    if check.returncode != 0:
        msg = f"commit {sha} is not on {source}'s {branch} branch. {REFUSED}"
        raise IntegrityError(msg)
