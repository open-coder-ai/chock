"""Emit a Devin plugin (`.devin-plugin/`) from a policy directory."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agentseam import packaging

from chock.compile.emitters.in_agent import _guard_script, tool_use_gate_spec
from chock.compile.emitters.in_agent_hooks import hooks_map_file
from chock.hooks import launch
from chock.plugin import gate_package, posture, store
from chock.plugin.build import (
    LICENSE_REL,
    _one_line,
    advisory_note,
    build_skill,
    license_text,
    plugin_name,
    skill_assets,
)
from chock.plugin.claude import POSTURE_ADVISORY, _runtime_files
from chock.plugin.store import SCRIPTS_TEMPLATE as _SCRIPTS_TEMPLATE

_LAYOUT = packaging.layout("devin")
HOOKS_REL = packaging.supports("devin", packaging.HOOKS)

#: agentseam records no `declares` convention for Devin (unlike codex_cli/cursor's
#: "./skills"): the vendor's own manifest doc says only "plugin-root-relative, no ..", so
#: this is the plainest value that satisfies that, not a borrowed one.
SKILLS_DECLARED_REL = "skills"

#: Devin's manifest fields, per the vendor's plugin reference: name, version, description,
#: skills. No author/license/repository/keywords/interface/hooks -- none of those are
#: documented for this manifest, and hooks.json is auto-discovered at the plugin root
#: rather than declared here (unlike codex_cli/cursor, whose manifests must point at
#: `./hooks/hooks.json`).
MANIFEST_KEYS = (
    "name",
    "version",
    "description",
    "skills",
)

POSTURE_BESTEFFORT_DEVIN = posture.enforced_devin()

_BESTEFFORT_NOTE_DEVIN = (
    "This policy ships a PreToolUse hook in this plugin's hooks.json, best-effort in Devin: "
    "fail-open by the vendor's own design, subject to the fail conditions stated in the "
    "plugin description. Repo-wide git-hook and CI coverage still needs `chock sync`. "
    "See https://github.com/open-coder-ai/chock"
)

#: Devin documents that hook commands receive this environment variable, not a `${...}` token
#: expandable inside a hooks.json string -- agentseam's `plugin_root("devin")` is None, so
#: `packaging.executable_ref` returns None for this vendor, unlike codex_cli/cursor's
#: `${PLUGIN_ROOT}`/`${CURSOR_PLUGIN_ROOT}`. Devin runs `type: command` hook entries "the same
#: format as Claude Code hooks", which executes them through a shell, so a shell expansion of
#: the documented variable is chock's own construction here, not a vendor-recorded token.
DEVIN_PLUGIN_ROOT_VAR = "DEVIN_PLUGIN_ROOT"


def _hook_command(script: str) -> str:
    """One interpreter invocation, via a shell expansion of `$DEVIN_PLUGIN_ROOT`."""
    adapter = f"${DEVIN_PLUGIN_ROOT_VAR}/{_SCRIPTS_TEMPLATE.format(name='devin.py')}"
    launcher = launch.plugin_interpreter(
        f'"${DEVIN_PLUGIN_ROOT_VAR}/{_SCRIPTS_TEMPLATE.format(name=launch.PLUGIN_LAUNCHER)}"'
    )
    guard = f"${DEVIN_PLUGIN_ROOT_VAR}/{_SCRIPTS_TEMPLATE.format(name=script)}"
    return f'{launcher} "{adapter}" --guard "{guard}"'


POSTURE_GATE_DEVIN = gate_package.gate_posture(
    "devin",
    "In the vendor's own words, plugin hooks are best effort and fail open, documented for local Devin sessions only.",
)
_GATE_NOTE_DEVIN = gate_package.gate_skill_note("devin")


def _gate_command() -> str:
    """The same adapter, handed the packaged gate instead of a guard."""
    adapter = f"${DEVIN_PLUGIN_ROOT_VAR}/{_SCRIPTS_TEMPLATE.format(name='devin.py')}"
    launcher = launch.plugin_interpreter(
        f'"${DEVIN_PLUGIN_ROOT_VAR}/{_SCRIPTS_TEMPLATE.format(name=launch.PLUGIN_LAUNCHER)}"'
    )
    gate = f"${DEVIN_PLUGIN_ROOT_VAR}/{_SCRIPTS_TEMPLATE.format(name='gate.json')}"
    return f'{launcher} "{adapter}" --gate "{gate}"'


def build_devin_manifest(
    manifest: dict[str, Any], policy_dir: Path, *, enforced: bool, gate: bool = False
) -> dict[str, Any]:
    """Derive `.devin-plugin/plugin.json` from a policy manifest."""
    policy_id = str(manifest.get("id") or Path(policy_dir).name)
    posture_text = (POSTURE_GATE_DEVIN if gate else POSTURE_BESTEFFORT_DEVIN) if enforced else POSTURE_ADVISORY

    description = _one_line(manifest.get("description"))

    data: dict[str, Any] = {
        "name": plugin_name(policy_id),
        "description": f"{description} [{posture_text}]".strip(),
        "skills": SKILLS_DECLARED_REL,
    }
    if manifest.get("version"):
        data["version"] = str(manifest["version"])
    return {key: data[key] for key in MANIFEST_KEYS if key in data}


def devin_plugin_files(policy_dir: Path, manifest: dict[str, Any], repo_root: Path) -> dict[Path, str]:
    """The Devin plugin's files as {relative path: content}, writing nothing."""
    policy_dir = Path(policy_dir)
    policy_id = str(manifest.get("id") or policy_dir.name)
    name = plugin_name(policy_id)
    script = _guard_script(policy_dir, policy_id)
    gate = None if script or not gate_package.gate_reaches("devin") else tool_use_gate_spec(policy_dir, Path(repo_root))
    enforced = script is not None or gate is not None

    skill = build_skill(policy_dir, manifest, Path(repo_root), hooks=HOOKS_REL if enforced else None)
    generic = advisory_note(policy_dir, manifest)
    if script:
        skill = skill.replace(generic, _BESTEFFORT_NOTE_DEVIN)
    elif gate:
        skill = skill.replace(generic, _GATE_NOTE_DEVIN)

    files: dict[Path, str] = {
        Path(_LAYOUT["manifest"]): json.dumps(
            build_devin_manifest(manifest, policy_dir, enforced=enforced, gate=gate is not None), indent=2
        )
        + "\n",
        Path(packaging.supports("devin", packaging.SKILL).format(name=name)): skill,
    }
    for rel, content in skill_assets(policy_dir).items():
        files[Path(packaging.supports("devin", packaging.SKILL).format(name=name)).parent / rel] = content
    licence = license_text(manifest)
    if licence:
        files[LICENSE_REL] = licence
    if script:
        files[Path(HOOKS_REL)] = json.dumps(hooks_map_file("devin", _hook_command(script)), indent=2) + "\n"
        files.update(_runtime_files("devin"))
        files.update(store.guard_files(policy_dir, script))
    elif gate:
        files[Path(HOOKS_REL)] = json.dumps(gate_package.gate_hooks_file("devin", _gate_command()), indent=2) + "\n"
        files.update(_runtime_files("devin"))
        files.update(gate_package.packaged_gate_files(policy_dir, gate, _SCRIPTS_TEMPLATE))
    return files


def stale_devin_files(policy_dir: Path, manifest: dict[str, Any], repo_root: Path, out_dir: Path) -> list[Path]:
    """Files under this package that the current manifest would no longer produce."""
    return store.stale_store_files("devin", devin_plugin_files, policy_dir, manifest, repo_root, out_dir)


def build_devin_plugin(policy_dir: Path, manifest: dict[str, Any], repo_root: Path, out_dir: Path) -> list[Path]:
    """Write the Devin package for one policy into a distribution directory."""
    return store.build_store_plugin("devin", devin_plugin_files, policy_dir, manifest, repo_root, out_dir)


def devin_plugin_differences(policy_dir: Path, manifest: dict[str, Any], repo_root: Path, out_dir: Path) -> list[str]:
    """Report where the on-disk Devin plugin disagrees with what the manifest would produce."""
    return store.store_plugin_differences("devin", devin_plugin_files, policy_dir, manifest, repo_root, out_dir)
