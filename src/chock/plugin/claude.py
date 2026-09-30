"""Emit a Claude-format plugin from a policy directory."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agentseam import packaging

from chock.compile.emitters.in_agent import GATE_FILE, _guard_script, tool_use_gate_spec
from chock.compile.emitters.in_agent_hooks import hooks_map_file
from chock.gate import runtime_bundle
from chock.hooks import launch
from chock.plugin import gate_package, store
from chock.plugin.build import (
    LICENSE_REL,
    _author,
    _keywords,
    _one_line,
    advisory_note,
    build_skill,
    license_text,
    plugin_name,
    skill_assets,
)
from chock.plugin.store import SCRIPTS_TEMPLATE as _SCRIPTS_TEMPLATE

_MANIFEST_REL = packaging.layout("claude_code")["manifest"]

POSTURE_ENFORCED = (
    "Session-enforced via a PreToolUse hook; needs git, a usable bash and a Python 3.11+ "
    "(python3, python or py, whichever actually runs; the Windows Store stub is skipped). With no "
    "working Python the hook refuses (exit 2); without git or bash, fail-open clients allow "
    "silently and fail-closed clients refuse matched commands. If the guard itself crashes or "
    "times out, the hook asks for confirmation rather than allowing silently."
)
POSTURE_ENFORCED_GATE = gate_package.gate_posture("claude_code")
POSTURE_ADVISORY = "Advisory skill only; enforcement needs chock installed in the repo."

_ENFORCED_NOTE = (
    "This policy is enforced in this client by a PreToolUse hook installed with the plugin, "
    "subject to the fail conditions stated in the plugin description. Repo-wide "
    "enforcement across every commit and in CI still needs `chock sync`. "
    "See https://github.com/open-coder-ai/chock"
)

_GATE_REL = _SCRIPTS_TEMPLATE.format(name=GATE_FILE)


def _adapter_source(agent: str = "claude_code") -> str:
    """`agent`'s self-contained runtime, verbatim -- agentseam's bundle plus chock's own"""
    return runtime_bundle.render(agent)


_LAUNCHER_REL = _SCRIPTS_TEMPLATE.format(name=launch.PLUGIN_LAUNCHER)


def _runtime_files(agent: str) -> dict[Path, str]:
    """`agent`'s runtime, and the launcher that starts it with a Python that actually runs."""
    return {
        Path(_SCRIPTS_TEMPLATE.format(name=f"{agent}.py")): _adapter_source(agent),
        Path(_LAUNCHER_REL): launch.launcher_text(),
    }


def _interpreter(agent: str) -> str:
    """The launcher invocation for `agent`'s plugin, reached through its plugin-root token."""
    return launch.plugin_interpreter(f'"{packaging.executable_ref(agent, _LAUNCHER_REL)}"')


def _hook_command(script: str) -> str:
    """One interpreter invocation, deliberately without a fallback chain."""
    adapter = packaging.executable_ref("claude_code", _SCRIPTS_TEMPLATE.format(name="claude_code.py"))
    guard = packaging.executable_ref("claude_code", _SCRIPTS_TEMPLATE.format(name=script))
    return f'{_interpreter("claude_code")} "{adapter}" --guard "{guard}"'


def _gate_command() -> str:
    """The same adapter, handed the packaged gate instead of a guard."""
    adapter = packaging.executable_ref("claude_code", _SCRIPTS_TEMPLATE.format(name="claude_code.py"))
    gate = packaging.executable_ref("claude_code", _GATE_REL)
    return f'{_interpreter("claude_code")} "{adapter}" --gate "{gate}"'


def build_claude_manifest(
    manifest: dict[str, Any], policy_dir: Path, *, enforced: bool, gate: bool = False
) -> dict[str, Any]:
    """Derive `.claude-plugin/plugin.json` from a policy manifest."""
    policy_id = manifest.get("id") or Path(policy_dir).name
    provenance = manifest.get("provenance") or {}
    posture = (POSTURE_ENFORCED_GATE if gate else POSTURE_ENFORCED) if enforced else POSTURE_ADVISORY

    data: dict[str, Any] = {
        "name": plugin_name(str(policy_id)),
        "description": f"{_one_line(manifest.get('description'))} [{posture}]",
        "keywords": _keywords(manifest),
    }
    if manifest.get("version"):
        data["version"] = str(manifest["version"])
    author = _author(provenance)
    if author:
        data["author"] = author
    if provenance.get("license"):
        data["license"] = str(provenance["license"])
    if provenance.get("source_repo"):
        data["repository"] = str(provenance["source_repo"])
    return data


def claude_plugin_files(policy_dir: Path, manifest: dict[str, Any], repo_root: Path) -> dict[Path, str]:
    """The Claude plugin's files as {relative path: content}, writing nothing."""
    policy_dir = Path(policy_dir)
    policy_id = manifest.get("id") or policy_dir.name
    name = plugin_name(str(policy_id))
    script = _guard_script(policy_dir, str(policy_id))
    gate = None if script else tool_use_gate_spec(policy_dir, Path(repo_root))
    enforced = script is not None or gate is not None

    skill = build_skill(policy_dir, manifest, Path(repo_root), hooks="hooks/hooks.json" if enforced else None)
    generic = advisory_note(policy_dir, manifest)
    if script:
        skill = skill.replace(generic, _ENFORCED_NOTE)
    elif gate:
        skill = skill.replace(generic, gate_package.gate_skill_note("claude_code", gate.get("action")))

    skill_rel = Path(packaging.supports("claude_code", packaging.SKILL).format(name=name))
    files: dict[Path, str] = {
        Path(_MANIFEST_REL): json.dumps(
            build_claude_manifest(manifest, policy_dir, enforced=enforced, gate=gate is not None), indent=2
        )
        + "\n",
        skill_rel: skill,
    }
    for rel, content in skill_assets(policy_dir).items():
        files[skill_rel.parent / rel] = content
    licence = license_text(manifest)
    if licence:
        files[LICENSE_REL] = licence
    hooks_rel = Path(packaging.supports("claude_code", packaging.HOOKS))
    if script:
        files[hooks_rel] = json.dumps(hooks_map_file("claude_code", _hook_command(script)), indent=2) + "\n"
        files.update(_runtime_files("claude_code"))
        files.update(store.guard_files(policy_dir, script))
    elif gate:
        files[hooks_rel] = json.dumps(gate_package.gate_hooks_file("claude_code", _gate_command()), indent=2) + "\n"
        files.update(_runtime_files("claude_code"))
        files.update(gate_package.packaged_gate_files(policy_dir, gate, _SCRIPTS_TEMPLATE))
    return files


def stale_claude_files(policy_dir: Path, manifest: dict[str, Any], repo_root: Path, out_dir: Path) -> list[Path]:
    """Files under this package that the current manifest would no longer produce."""
    return store.stale_store_files("claude", claude_plugin_files, policy_dir, manifest, repo_root, out_dir)


def build_claude_plugin(policy_dir: Path, manifest: dict[str, Any], repo_root: Path, out_dir: Path) -> list[Path]:
    """Write the Claude-format package for one policy into a distribution directory."""
    return store.build_store_plugin("claude", claude_plugin_files, policy_dir, manifest, repo_root, out_dir)


def claude_plugin_differences(policy_dir: Path, manifest: dict[str, Any], repo_root: Path, out_dir: Path) -> list[str]:
    """Report where the on-disk Claude plugin disagrees with what the manifest would produce."""
    return store.store_plugin_differences("claude", claude_plugin_files, policy_dir, manifest, repo_root, out_dir)
