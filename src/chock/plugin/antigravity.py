"""Emit an Antigravity plugin: `plugin.json` (`name`, `description`) plus a root `hooks.json`."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from chock.plugin import gate_package, guard_gate, hook_dir, posture
from chock.plugin.build import PluginNameError, _one_line, plugin_name
from chock.plugin.claude import POSTURE_ADVISORY

#: The CLI's manifest schema (antigravity.google/docs/cli/plugins): `name` required, this pattern,
#: `additionalProperties: false` over `name` and `description` -- so no version, author or `$schema`.
_NAME = re.compile(r"^[a-zA-Z0-9-_]+$")
MANIFEST_KEYS = ("name", "description")

_CAVEAT = (
    "Antigravity documents no fail mode for a hook and no plugin-root variable, so the hook names this "
    "plugin's folder by absolute path: moving the folder stops the hook."
)
POSTURE_BESTEFFORT = (
    "Best-effort in Antigravity by a PreToolUse hook in the plugin's hooks.json "
    f"({posture.witness_clause('antigravity')}). {_CAVEAT} {hook_dir.POSTURE_TAIL}"
)
POSTURE_GATE = gate_package.gate_posture("antigravity", _CAVEAT)

GUARD_NOTE = (
    "This policy ships a PreToolUse hook in this plugin's hooks.json, best-effort in Antigravity, "
    "subject to the fail conditions stated in the plugin description. Repo-wide git-hook and CI "
    "coverage still needs `chock sync`. See https://github.com/open-coder-ai/chock"
)


def manifest_posture(*, enforced: bool, gate: bool = False, guard: bool = False) -> str:
    """The posture sentence a package's description ends with; `guard` with `gate` states both halves."""
    if not enforced:
        return POSTURE_ADVISORY
    return guard_gate.posture(POSTURE_BESTEFFORT, POSTURE_GATE, guard=guard or not gate, gate=gate)


def build_antigravity_manifest(
    manifest: dict[str, Any], policy_dir: Path, *, enforced: bool, gate: bool = False, guard: bool = False
) -> dict[str, Any]:
    """Derive `plugin.json` from a policy manifest: the schema's two fields only."""
    name = plugin_name(str(manifest.get("id") or Path(policy_dir).name))
    if not _NAME.match(name):
        msg = f"{name!r} is not a valid Antigravity plugin name: letters, digits, '-' and '_' only"
        raise PluginNameError(msg)
    posture = manifest_posture(enforced=enforced, gate=gate, guard=guard)
    data = {"name": name, "description": f"{_one_line(manifest.get('description'))} [{posture}]".strip()}
    return {key: data[key] for key in MANIFEST_KEYS}


SPEC = hook_dir.Spec("antigravity", "antigravity", GUARD_NOTE, build_antigravity_manifest)


def antigravity_plugin_files(
    policy_dir: Path, manifest: dict[str, Any], repo_root: Path, *, folded: bool = True
) -> dict[Path, str]:
    """The Antigravity plugin's files as {relative path: content}, writing nothing; the root left unresolved."""
    return hook_dir.plugin_files(SPEC, policy_dir, manifest, repo_root, folded=folded)


def build_antigravity_plugin(policy_dir: Path, manifest: dict[str, Any], repo_root: Path, out_dir: Path) -> list[Path]:
    """Write the Antigravity package for one policy into a distribution directory."""
    return hook_dir.build(SPEC, policy_dir, manifest, repo_root, out_dir)


def antigravity_plugin_differences(
    policy_dir: Path, manifest: dict[str, Any], repo_root: Path, out_dir: Path
) -> list[str]:
    """Report where the on-disk Antigravity plugin disagrees with what the manifest would produce."""
    return hook_dir.differences(SPEC, policy_dir, manifest, repo_root, out_dir)
