"""Git-hook-arming logic for a fresh clone's first Claude Code session."""

from __future__ import annotations

import os
import subprocess
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
        return True
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
