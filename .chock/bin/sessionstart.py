#!/usr/bin/env python3
"""Chock SessionStart adapter — SELF-CONTAINED, STDLIB ONLY.

Copied verbatim to <repo>/.chock/bin/sessionstart.py by `chock sync`.

Git never clones hooks — by design, because "cloning a repo executes the repo's
code" would be remote code execution — so a fresh clone of a Chock repo enforces
nothing at commit time until `chock sync` runs. This adapter closes that gap for
Claude Code: it runs when a session opens (wired as a SessionStart hook in the
committed .claude/settings.json, consented through Claude Code's workspace-trust
prompt), and either stays silent because the hooks are already armed, arms them
with the chock CLI when it is importable, or prints the one command to run.
Stdout from a SessionStart hook is added to the session context, so the
instruction reaches the agent, not a log nobody reads.

Always exits 0: an unarmed clone must degrade to advice, never block a session.

Usage (from a settings.json SessionStart hook):
  python .chock/bin/sessionstart.py
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

_INSTRUCTION = (
    "Chock: this clone's git hooks are NOT installed -- git never clones hooks, "
    "so commit-time gates will not run locally until someone runs:\n"
    "    pip install chock && chock sync --repo .\n"
    "Run that before the first commit. (The repo's CI gate, where wired, enforces regardless.)"
)


def _repo_root() -> Path:
    root = os.environ.get("CLAUDE_PROJECT_DIR")
    return Path(root) if root else Path.cwd()


def _hooks_pre_commit(repo_root: Path) -> Path | None:
    """The active pre-commit hook path, honouring core.hooksPath. None when git is absent."""
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--git-path", "hooks"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    hooks = Path(proc.stdout.strip())
    if not hooks.is_absolute():
        hooks = repo_root / hooks
    return hooks / "pre-commit"


def _armed(repo_root: Path) -> bool:
    pre_commit = _hooks_pre_commit(repo_root)
    if pre_commit is None:
        return True  # no git (or not a repo): nothing to arm, stay silent
    try:
        return pre_commit.exists() and "chock" in pre_commit.read_text(encoding="utf-8", errors="replace").lower()
    except OSError:
        return False


def _chock_importable() -> bool:
    import importlib.util

    try:
        return importlib.util.find_spec("chock") is not None
    except (ImportError, ValueError):
        return False


def main() -> int:
    repo_root = _repo_root()
    if not (repo_root / ".chock").is_dir():
        return 0  # not a chock-managed repo
    if _armed(repo_root):
        return 0

    if _chock_importable():
        try:
            proc = subprocess.run(
                [sys.executable, "-m", "chock", "sync", "--repo", str(repo_root)],
                cwd=repo_root,
                capture_output=True,
                text=True,
                timeout=240,
            )
        except (OSError, subprocess.TimeoutExpired):
            proc = None
        if proc is not None and proc.returncode == 0 and _armed(repo_root):
            print(
                "Chock: this clone's git hooks were not installed (git never clones hooks); "
                "armed them now with `chock sync`."
            )
            return 0

    print(_INSTRUCTION)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
