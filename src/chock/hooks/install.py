#!/usr/bin/env python3
"""Install the Chock validation and policy hooks as dispatcher-based implementations."""

from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path

from chock.hooks.in_agent_install import WIRED_VENDORS, install_hooks, install_label
from chock.hooks.installers import (
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
from chock.hooks.sessionstart_install import install_sessionstart_hook
from chock.output import error, warn
from chock.scaffold.recompile import refresh_after_install

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
        git = shutil.which("git") or "git"
        repo_root = Path(
            subprocess.check_output(  # noqa: S603 -- finding the repo root via git is this branch's job
                [git, "rev-parse", "--show-toplevel"], text=True, encoding="utf-8", errors="replace"
            ).strip()
        )
    if not is_git_repo(repo_root):
        error(NOT_A_GIT_REPO.format(root=repo_root))
        return 1

    hooks_dir = get_hooks_dir(repo_root)
    hooks_dir.mkdir(parents=True, exist_ok=True)

    install_validate_hook(hooks_dir, repo_root)
    install_policy_hooks(repo_root, hooks_dir)

    wired = False
    for vendor in WIRED_VENDORS:
        try:
            installed = install_hooks(repo_root, vendor)
        except ValueError as exc:
            warn(str(exc))
        else:
            if installed:
                print(f"Registered {len(installed)} {install_label(vendor)}")
                wired = True
    if wired:
        refresh_after_install(repo_root)

    try:
        if install_sessionstart_hook(repo_root):
            print("Registered SessionStart arm hook in .claude/settings.json")
    except ValueError as exc:
        warn(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
