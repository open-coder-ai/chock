"""Emit a goose plugin: a manifest-less folder with `hooks/hooks.json`, loaded from `.agents/plugins/<name>/`."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from chock.plugin import hook_dir, posture

#: goose runs every hook with `sh -c` and denies a PreToolUse call whose hook fails (`on_failure: block`, which agentseam
#: writes on every entry): without sh every call was denied (org-plan witness/results/witness-goose-2026-10-18.md).
GUARD_NOTE = (
    "This policy ships a PreToolUse hook in this plugin's hooks/hooks.json with `on_failure: block`, "
    "so goose denies the tool call when the hook fails to run or answer "
    f"({posture.witness_clause('goose')}); goose's Stop hooks stay fail-open. goose runs every hook with "
    "`sh -c`, so the hook needs sh (on Windows, Git for Windows' sh), git and a Python 3.11+ on PATH; without "
    "sh every tool call is denied. Repo-wide git-hook and CI coverage still needs `chock sync`. "
    "See https://github.com/open-coder-ai/chock"
)


SPEC = hook_dir.Spec("goose", "goose", GUARD_NOTE)


def goose_plugin_files(
    policy_dir: Path, manifest: dict[str, Any], repo_root: Path, *, folded: bool = True
) -> dict[Path, str]:
    """The goose plugin's files as {relative path: content}, writing nothing."""
    return hook_dir.plugin_files(SPEC, policy_dir, manifest, repo_root, folded=folded)


def build_goose_plugin(policy_dir: Path, manifest: dict[str, Any], repo_root: Path, out_dir: Path) -> list[Path]:
    """Write the goose package for one policy into a distribution directory."""
    return hook_dir.build(SPEC, policy_dir, manifest, repo_root, out_dir)


def goose_plugin_differences(policy_dir: Path, manifest: dict[str, Any], repo_root: Path, out_dir: Path) -> list[str]:
    """Report where the on-disk goose plugin disagrees with what the manifest would produce."""
    return hook_dir.differences(SPEC, policy_dir, manifest, repo_root, out_dir)
