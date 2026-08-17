#!/usr/bin/env python3
"""Install the Chock validation and policy hooks as dispatcher-based implementations.

The installer creates pre-commit and pre-push dispatchers that run every executable script
in .git/hooks/<event>.d/. Existing hooks are backed up before being replaced.
The dispatcher respects `core.hooksPath`.

Usage:
  chock sync
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

# Re-exported: the installers moved to `installers.py` (so `scaffold.recompile` can use
# them without importing this entrypoint, which imports the orchestrator back), but every
# historical caller imports them from here.
from chock.hooks.installers import (  # noqa: F401
    DISPATCHER_TEMPLATE,
    GENERATED_MARKER,
    INTERPRETER_PLACEHOLDER,
    NOT_A_GIT_REPO,
    _discover_policy_hooks,
    _render_hook,
    _repo_relative,
    get_hooks_dir,
    install_dispatcher,
    install_policy_hooks,
    install_validate_hook,
    is_git_repo,
    relocate_existing_hook,
)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Install Chock git hooks")
    parser.add_argument("repo_root", nargs="?", default=None, help="Repository root (default: current git top-level)")
    args = parser.parse_args(argv)

    if args.repo_root:
        repo_root = Path(args.repo_root).resolve()
    else:
        repo_root = Path(
            subprocess.check_output(
                ["git", "rev-parse", "--show-toplevel"], text=True, encoding="utf-8", errors="replace"
            ).strip()
        )
    if not is_git_repo(repo_root):
        print(f"[ERROR] {NOT_A_GIT_REPO.format(root=repo_root)}", file=sys.stderr)
        return 1

    hooks_dir = get_hooks_dir(repo_root)
    hooks_dir.mkdir(parents=True, exist_ok=True)

    install_validate_hook(hooks_dir, repo_root)
    install_policy_hooks(repo_root, hooks_dir)

    # PreToolUse fragments were compiled but never installed, so the policies that rely on
    # them enforced nothing while coverage reported otherwise. Cursor's hook config gets
    # the identical treatment: install both, then derive coverage once.
    from chock.hooks.cursor_install import install_cursor_hooks
    from chock.hooks.pretooluse_install import install_pretooluse_hooks

    wired = False
    try:
        installed = install_pretooluse_hooks(repo_root)
    except ValueError as exc:
        print(f"[WARN] {exc}", file=sys.stderr)
    else:
        if installed:
            print(f"Registered {len(installed)} PreToolUse hook(s) in .claude/settings.json")
            wired = True
    try:
        cursor_installed = install_cursor_hooks(repo_root)
    except ValueError as exc:
        print(f"[WARN] {exc}", file=sys.stderr)
    else:
        if cursor_installed:
            print(f"Registered {len(cursor_installed)} Cursor hook entr(y/ies) in .cursor/hooks.json")
            wired = True
    if wired:
        # Installing changed what is enforced, and coverage is derived from that.
        from chock.scaffold.recompile import refresh_after_install

        refresh_after_install(repo_root)

    # No coverage interaction: the arm hook is repo wiring (it installs the git hooks on
    # a fresh clone), not a policy surface, so it can follow the refresh safely.
    from chock.hooks.sessionstart_install import install_sessionstart_hook

    try:
        if install_sessionstart_hook(repo_root):
            print("Registered SessionStart arm hook in .claude/settings.json")
    except ValueError as exc:
        print(f"[WARN] {exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
