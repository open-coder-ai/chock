"""Git-hook-arming logic for a fresh clone's first Claude Code session.

Git never clones hooks -- by design, because "cloning a repo executes the repo's code"
would be remote code execution -- so a fresh clone of a Chock repo enforces nothing at
commit time until `chock sync` runs. This closes that gap for Claude Code: wired as the
`session_start` branch of the vendored claude_code runtime (`gate/runtime_bundle.py`
source-extracts these functions into it), it either stays silent because the hooks are
already armed, arms them with the chock CLI when it is importable, or returns an
`additionalContext` instruction naming the one command to run. Never blocks: an unarmed
clone must degrade to advice, never stop a session.

Not vendored on its own -- these functions exist only to be source-extracted (the same
technique `agentseam.bundler` uses on its own adapter modules) into the claude_code
runtime's handler, alongside the guard-running logic in `gate/guard_runner.py`. Stays
stdlib-only for exactly that reason.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

# Not dead: source-extracted (see module docstring) into gate/runtime_bundle.py's
# vendored claude_code runtime, which references it as `_INSTRUCTION` in the spliced
# SessionStart handler. CodeQL analyses this module in isolation and has no model for
# that extraction, so it cannot see the use.
# codeql[py/unused-global-variable]
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
