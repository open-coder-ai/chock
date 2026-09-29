"""The throwaway repository an eval case replays in."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

GIT = shutil.which("git") or "git"


def git(repo: Path, *args: str, stdin: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(  # noqa: S603 -- fixture harness: replays a case's own git commands
        [GIT, *args],
        cwd=str(repo),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        input=stdin,
        check=False,
    )


def init_repo(repo: Path) -> None:
    """A repo with one commit, so HEAD resolves and added lines diff against something."""
    git(repo, "init", "--quiet", "--initial-branch=main", ".")
    git(repo, "config", "user.email", "eval@chock.invalid")
    git(repo, "config", "user.name", "Chock Eval")
    git(repo, "config", "commit.gpgsign", "false")


def write_files(repo: Path, files: dict[str, Any]) -> list[str]:
    written: list[str] = []
    for rel, content in (files or {}).items():
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(content), encoding="utf-8", newline="\n")
        written.append(rel)
    return written


def prepare(repo: Path, spec: dict[str, Any]) -> None:
    """Build the repository state the case describes, up to but not including the gate run."""
    init_repo(repo)

    head_files = spec.get("head_files") or {}
    if head_files:
        write_files(repo, head_files)
        git(repo, "add", *sorted(head_files))
    git(repo, "commit", "--allow-empty", "-m", "baseline")

    branch = spec.get("branch")
    if branch and branch != "main":
        git(repo, "checkout", "-q", "-b", str(branch))

    write_files(repo, spec.get("repo_files") or {})

    staged = write_files(repo, spec.get("files") or {})
    if staged:
        git(repo, "add", *sorted(staged))
