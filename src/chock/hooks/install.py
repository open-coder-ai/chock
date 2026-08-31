#!/usr/bin/env python3
"""Install the Chock validation and policy hooks as dispatcher-based implementations."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

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

__all__ = [
    "DISPATCHER_TEMPLATE",
    "GENERATED_MARKER",
    "INTERPRETER_PLACEHOLDER",
    "NOT_A_GIT_REPO",
    "_discover_policy_hooks",
    "_render_hook",
    "_repo_relative",
    "get_hooks_dir",
    "install_dispatcher",
    "install_policy_hooks",
    "install_validate_hook",
    "is_git_repo",
    "relocate_existing_hook",
]


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

    from chock.hooks.agenthooks_install import install_agent_hooks
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
    try:
        agent_installed = install_agent_hooks(repo_root)
    except ValueError as exc:
        print(f"[WARN] {exc}", file=sys.stderr)
    else:
        if agent_installed:
            print(f"Registered {len(agent_installed)} agent hook(s) in .github/hooks/chock.json")
            wired = True
    if wired:
        from chock.scaffold.recompile import refresh_after_install

        refresh_after_install(repo_root)

    from chock.hooks.sessionstart_install import install_sessionstart_hook

    try:
        if install_sessionstart_hook(repo_root):
            print("Registered SessionStart arm hook in .claude/settings.json")
    except ValueError as exc:
        print(f"[WARN] {exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
