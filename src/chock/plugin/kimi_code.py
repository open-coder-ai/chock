"""Emit a Kimi Code plugin: `kimi.plugin.json` carrying its `hooks` array, installed with `/plugins install <path>`.

Kimi reads plugin hooks from the manifest, not a file, so the hooks document is built at the store's
`hooks` path like every other client's and folded into the manifest when written (`hook_dir.fold`).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from chock.plugin import gate_package, guard_gate, hook_dir
from chock.plugin.build import PluginNameError, _one_line, plugin_name
from chock.plugin.claude import POSTURE_ADVISORY

#: The manifest reference: "`name` | Required; serves as the plugin id. Must match `[a-z0-9][a-z0-9_-]{0,63}`".
_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
#: Without `skills`, Kimi reads a root SKILL.md only; chock's skills live under skills/<name>/.
SKILLS = "./skills/"
MANIFEST_KEYS = ("name", "version", "description", "skills", "hooks")

_CAVEAT = (
    "Kimi Code's hooks documentation says a hook that errors or times out lets the call through and that hooks "
    "should not be the sole security barrier; Kimi cannot prompt, so an ask is not enforced there, and a plugin "
    "applies to every project of the user who installed it."
)
POSTURE_BESTEFFORT = (
    "Best-effort in Kimi Code by a PreToolUse hook in the plugin's kimi.plugin.json (documented by the vendor; "
    f"not witnessed by chock). {_CAVEAT} {hook_dir.POSTURE_TAIL}"
)
POSTURE_GATE = gate_package.gate_posture("kimi_code", _CAVEAT)

GUARD_NOTE = (
    "This policy ships a PreToolUse hook in this plugin's kimi.plugin.json, best-effort in Kimi Code, "
    "subject to the fail conditions stated in the plugin description. Repo-wide git-hook and CI "
    "coverage still needs `chock sync`. See https://github.com/open-coder-ai/chock"
)


def manifest_posture(*, enforced: bool, gate: bool = False, guard: bool = False) -> str:
    """The posture sentence a package's description ends with; `guard` with `gate` states both halves."""
    if not enforced:
        return POSTURE_ADVISORY
    return guard_gate.posture(POSTURE_BESTEFFORT, POSTURE_GATE, guard=guard or not gate, gate=gate)


def build_kimi_manifest(
    manifest: dict[str, Any], policy_dir: Path, *, enforced: bool, gate: bool = False, guard: bool = False
) -> dict[str, Any]:
    """Derive `kimi.plugin.json` from a policy manifest; its `hooks` array is folded in when written."""
    name = plugin_name(str(manifest.get("id") or Path(policy_dir).name))
    if not _NAME.match(name):
        msg = f"{name!r} is not a valid Kimi Code plugin name: [a-z0-9][a-z0-9_-]{{0,63}}"
        raise PluginNameError(msg)
    posture = manifest_posture(enforced=enforced, gate=gate, guard=guard)
    data = {
        "name": name,
        "version": str(manifest.get("version") or ""),
        "description": f"{_one_line(manifest.get('description'))} [{posture}]".strip(),
        "skills": SKILLS,
    }
    return {key: data[key] for key in MANIFEST_KEYS if data.get(key)}


SPEC = hook_dir.Spec("kimi", "kimi_code", GUARD_NOTE, build_kimi_manifest)


def kimi_plugin_files(
    policy_dir: Path, manifest: dict[str, Any], repo_root: Path, *, folded: bool = True
) -> dict[Path, str]:
    """The Kimi Code plugin's files as {relative path: content}, writing nothing; hooks not yet folded in."""
    return hook_dir.plugin_files(SPEC, policy_dir, manifest, repo_root, folded=folded)


def build_kimi_plugin(policy_dir: Path, manifest: dict[str, Any], repo_root: Path, out_dir: Path) -> list[Path]:
    """Write the Kimi Code package for one policy into a distribution directory."""
    return hook_dir.build(SPEC, policy_dir, manifest, repo_root, out_dir)


def kimi_plugin_differences(policy_dir: Path, manifest: dict[str, Any], repo_root: Path, out_dir: Path) -> list[str]:
    """Report where the on-disk Kimi Code plugin disagrees with what the manifest would produce."""
    return hook_dir.differences(SPEC, policy_dir, manifest, repo_root, out_dir)
