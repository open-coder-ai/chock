"""Review 4 helpers (pass-4 proofs): rewrite the base on `main`, then branch `pr` from it."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from floor_support import base_repo, commit, git, run_floor, write  # noqa: F401

FAKE_A = "1" * 40
FAKE_B = "2" * 40


def rebase_main(repo: Path, change) -> None:
    """Apply `change(repo)` on main as a new base commit, then put `pr` back on it."""
    git(repo, "checkout", "-q", "main")
    change(repo)
    commit(repo, "base edit")
    git(repo, "checkout", "-q", "-B", "pr")


def raw_commit(repo: Path, message: str) -> str:
    """Commit the index as it stands (no `add -A`), so a hand-made gitlink survives."""
    git(repo, "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-q", "--no-gpg-sign", "-m", message)
    return git(repo, "rev-parse", "HEAD")


def gitlink(repo: Path, path: str, sha: str) -> None:
    git(repo, "update-index", "--add", "--cacheinfo", f"160000,{sha},{path}")


def symlink(repo: Path, path: str, target: str) -> None:
    link = repo / path
    link.parent.mkdir(parents=True, exist_ok=True)
    if link.is_symlink() or link.is_file():
        link.unlink()
    elif link.is_dir():
        shutil.rmtree(link)
    os.symlink(target, link)


def rm(repo: Path, path: str) -> None:
    p = repo / path
    if p.is_symlink() or p.is_file():
        p.unlink()
    elif p.is_dir():
        shutil.rmtree(p)


HOOKLESS = {"hooks": {}}


def undecided(repo: Path, capsys, link: str) -> str:
    """S1: exit 2, naming the link that does not stay on the control plane, and the fix."""
    code, out = run_floor(repo, capsys)
    assert code == 2, out
    assert f"symbolic link {link} at" in out, out
    assert "replace the link with real files" in out, out
    return out
