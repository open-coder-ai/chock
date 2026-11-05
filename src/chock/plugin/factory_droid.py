"""Emit a Factory Droid plugin: `.factory-plugin/plugin.json` plus `hooks/hooks.json`.

Droid rejects a bare plugin folder: `chock install` wraps it in a local marketplace
(`.factory-plugin/marketplace.json`, data/install.json) for `droid plugin marketplace add`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from chock.plugin import gate_package, guard_gate, hook_dir
from chock.plugin.build import _one_line, plugin_name
from chock.plugin.claude import POSTURE_ADVISORY

#: Droid reads none of these ("Droid does not require or read the fields inside `plugin.json`"): source metadata only.
MANIFEST_KEYS = ("name", "version", "description")

_CAVEAT = (
    "Droid's hooks documentation says a non-zero exit other than 2 is a non-blocking error and the call proceeds, "
    "an org's allowManagedHooksOnly setting ignores this plugin's hooks, and agentseam records that Droid "
    "degrades an ask to a block."
)
POSTURE_BESTEFFORT = (
    "Best-effort in Factory Droid by a PreToolUse hook in the plugin's hooks/hooks.json (documented by the vendor; "
    f"not witnessed by chock). {_CAVEAT} {hook_dir.POSTURE_TAIL}"
)
POSTURE_GATE = gate_package.gate_posture("factory_droid", _CAVEAT)

GUARD_NOTE = (
    "This policy ships a PreToolUse hook in this plugin's hooks/hooks.json, best-effort in Factory Droid, "
    "subject to the fail conditions stated in the plugin description. Repo-wide git-hook and CI "
    "coverage still needs `chock sync`. See https://github.com/open-coder-ai/chock"
)


def manifest_posture(*, enforced: bool, gate: bool = False, guard: bool = False) -> str:
    """The posture sentence a package's description ends with; `guard` with `gate` states both halves."""
    if not enforced:
        return POSTURE_ADVISORY
    return guard_gate.posture(POSTURE_BESTEFFORT, POSTURE_GATE, guard=guard or not gate, gate=gate)


def build_droid_manifest(
    manifest: dict[str, Any], policy_dir: Path, *, enforced: bool, gate: bool = False, guard: bool = False
) -> dict[str, Any]:
    """Derive `.factory-plugin/plugin.json` from a policy manifest: name, version and description."""
    posture = manifest_posture(enforced=enforced, gate=gate, guard=guard)
    data = {
        "name": plugin_name(str(manifest.get("id") or Path(policy_dir).name)),
        "version": str(manifest.get("version") or ""),
        "description": f"{_one_line(manifest.get('description'))} [{posture}]".strip(),
    }
    return {key: data[key] for key in MANIFEST_KEYS if data[key]}


SPEC = hook_dir.Spec("droid", "factory_droid", GUARD_NOTE, build_droid_manifest)


def droid_plugin_files(
    policy_dir: Path, manifest: dict[str, Any], repo_root: Path, *, folded: bool = True
) -> dict[Path, str]:
    """The Droid plugin's files as {relative path: content}, writing nothing."""
    return hook_dir.plugin_files(SPEC, policy_dir, manifest, repo_root, folded=folded)


def build_droid_plugin(policy_dir: Path, manifest: dict[str, Any], repo_root: Path, out_dir: Path) -> list[Path]:
    """Write the Droid package for one policy into a distribution directory."""
    return hook_dir.build(SPEC, policy_dir, manifest, repo_root, out_dir)


def droid_plugin_differences(policy_dir: Path, manifest: dict[str, Any], repo_root: Path, out_dir: Path) -> list[str]:
    """Report where the on-disk Droid plugin disagrees with what the manifest would produce."""
    return hook_dir.differences(SPEC, policy_dir, manifest, repo_root, out_dir)
