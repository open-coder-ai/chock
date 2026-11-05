"""Emit an OpenHands plugin: `.plugin/plugin.json` plus `hooks/hooks.json`, loaded with `openhands --plugin <path>`.

OpenHands also reads the Claude Code layout (`.claude-plugin/`), but chock's Claude package does not serve it:
its hooks match Claude's tool names (Bash, Write) where OpenHands calls `terminal` and `file_editor`, its
runtime answers in Claude's grammar, and OpenHands sets no `CLAUDE_PLUGIN_ROOT`. So this is its own target.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from chock.plugin import gate_package, guard_gate, hook_dir
from chock.plugin.build import _one_line, plugin_name
from chock.plugin.claude import POSTURE_ADVISORY

MANIFEST_KEYS = ("name", "version", "description")

_CAVEAT = (
    "OpenHands documents no plugin-root variable, so the hook names this plugin's folder by absolute path: "
    "moving the folder stops the hook. Its hook runner blocks only on exit code 2 or a deny, and lets any "
    "other failure through."
)
POSTURE_BESTEFFORT = (
    "Best-effort in OpenHands by a PreToolUse hook in the plugin's hooks/hooks.json (documented by the vendor; "
    f"not witnessed by chock). {_CAVEAT} {hook_dir.POSTURE_TAIL}"
)
POSTURE_GATE = gate_package.gate_posture("openhands", _CAVEAT)

GUARD_NOTE = (
    "This policy ships a PreToolUse hook in this plugin's hooks/hooks.json, best-effort in OpenHands, "
    "subject to the fail conditions stated in the plugin description. Repo-wide git-hook and CI "
    "coverage still needs `chock sync`. See https://github.com/open-coder-ai/chock"
)


def manifest_posture(*, enforced: bool, gate: bool = False, guard: bool = False) -> str:
    """The posture sentence a package's description ends with; `guard` with `gate` states both halves."""
    if not enforced:
        return POSTURE_ADVISORY
    return guard_gate.posture(POSTURE_BESTEFFORT, POSTURE_GATE, guard=guard or not gate, gate=gate)


def build_openhands_manifest(
    manifest: dict[str, Any], policy_dir: Path, *, enforced: bool, gate: bool = False, guard: bool = False
) -> dict[str, Any]:
    """Derive `.plugin/plugin.json` from a policy manifest: name, version and description."""
    posture = manifest_posture(enforced=enforced, gate=gate, guard=guard)
    data = {
        "name": plugin_name(str(manifest.get("id") or Path(policy_dir).name)),
        "version": str(manifest.get("version") or ""),
        "description": f"{_one_line(manifest.get('description'))} [{posture}]".strip(),
    }
    return {key: data[key] for key in MANIFEST_KEYS if data[key]}


SPEC = hook_dir.Spec("openhands", "openhands", GUARD_NOTE, build_openhands_manifest)


def openhands_plugin_files(
    policy_dir: Path, manifest: dict[str, Any], repo_root: Path, *, folded: bool = True
) -> dict[Path, str]:
    """The OpenHands plugin's files as {relative path: content}, writing nothing; the root left unresolved."""
    return hook_dir.plugin_files(SPEC, policy_dir, manifest, repo_root, folded=folded)


def build_openhands_plugin(policy_dir: Path, manifest: dict[str, Any], repo_root: Path, out_dir: Path) -> list[Path]:
    """Write the OpenHands package for one policy into a distribution directory."""
    return hook_dir.build(SPEC, policy_dir, manifest, repo_root, out_dir)


def openhands_plugin_differences(
    policy_dir: Path, manifest: dict[str, Any], repo_root: Path, out_dir: Path
) -> list[str]:
    """Report where the on-disk OpenHands plugin disagrees with what the manifest would produce."""
    return hook_dir.differences(SPEC, policy_dir, manifest, repo_root, out_dir)
