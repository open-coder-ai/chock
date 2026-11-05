"""Emit a grok plugin: a manifest-less folder with `hooks/hooks.json`, installed with `grok plugin install --trust`."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from chock.plugin import hook_dir

GUARD_NOTE = (
    "This policy ships a PreToolUse hook in this plugin's hooks/hooks.json, best-effort in grok: "
    "grok's hooks documentation says every hook failure (a timeout, a crash, malformed output) fails "
    "open and only an explicit deny blocks, plugins stay off until enabled and trusted, and an "
    "allowManagedHooksOnly policy skips plugin hooks. The hook needs git and a Python 3.11+ on PATH. "
    "Repo-wide git-hook and CI coverage still needs `chock sync`. See https://github.com/open-coder-ai/chock"
)

SPEC = hook_dir.Spec("grok", "grok", GUARD_NOTE)


def grok_plugin_files(
    policy_dir: Path, manifest: dict[str, Any], repo_root: Path, *, folded: bool = True
) -> dict[Path, str]:
    """The grok plugin's files as {relative path: content}, writing nothing."""
    return hook_dir.plugin_files(SPEC, policy_dir, manifest, repo_root, folded=folded)


def build_grok_plugin(policy_dir: Path, manifest: dict[str, Any], repo_root: Path, out_dir: Path) -> list[Path]:
    """Write the grok package for one policy into a distribution directory."""
    return hook_dir.build(SPEC, policy_dir, manifest, repo_root, out_dir)


def grok_plugin_differences(policy_dir: Path, manifest: dict[str, Any], repo_root: Path, out_dir: Path) -> list[str]:
    """Report where the on-disk grok plugin disagrees with what the manifest would produce."""
    return hook_dir.differences(SPEC, policy_dir, manifest, repo_root, out_dir)
