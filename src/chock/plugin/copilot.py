"""Emit a GitHub Copilot (Agent Plugins 1.0 + hooks) plugin from a policy directory."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agentseam import packaging

from chock.compile.emitters.in_agent import _guard_script, tool_use_gate_spec
from chock.compile.emitters.in_agent_hooks import hooks_map_file
from chock.hooks import launch
from chock.plugin import gate_package, store
from chock.plugin.build import (
    LICENSE_REL,
    NAMESPACE,
    advisory_note,
    build_manifest,
    build_skill,
    license_text,
    plugin_name,
    skill_assets,
)
from chock.plugin.claude import POSTURE_ADVISORY, _runtime_files
from chock.plugin.store import SCRIPTS_TEMPLATE as _SCRIPTS_TEMPLATE

_LAYOUT = packaging.layout("copilot")
PLUGIN_ROOT = packaging.plugin_root("copilot")
HOOKS_REL = packaging.supports("copilot", packaging.HOOKS)

POSTURE_ENFORCED_COPILOT = (
    "Session-enforced by the PreToolUse hook under com.github.copilot/ in clients that "
    "read that namespace (documented for VS Code agent mode); a client that ignores it, "
    "as the Agent Plugins spec tells generic clients to, gets the advisory skill only. "
    "The hook needs git, a usable bash and a Python 3.11+ (python3, python or py, whichever "
    "actually runs). With no working Python it exits 2; without git or bash, fail-open clients "
    "allow silently and fail-closed clients refuse matched commands. If the guard itself "
    "crashes or times out, the "
    "hook asks for confirmation rather than allowing silently -- VS Code agent mode honours "
    "that ask and it overrides the client's own auto-approve."
)

_COPILOT_ENFORCED_NOTE = (
    "This package ships a PreToolUse hook under com.github.copilot/. It enforces only in a "
    "client that both reads that namespace AND tells the hook where the package lives. A "
    "client that exports no plugin-root variable (VS Code's agent-plugin format exports none) "
    "runs the hook, which then exits 0 and checks nothing; a root that is set but lacks the "
    "bundled hook exits 2 and refuses the call. "
    "A client that ignores the namespace gets this text only. Repo-wide enforcement across "
    "every commit and in CI still needs `chock sync`. "
    "See https://github.com/open-coder-ai/chock"
)


_NO_ADAPTER_REFUSAL = (
    "chock: the plugin root is set but the bundled hook is missing, so this call cannot be "
    "checked. Refusing rather than allowing it unchecked."
)


def _root_guarded(target: str, flag: str) -> str:
    """One interpreter invocation: no plugin root allows (exit 0), a root without the adapter refuses (exit 2)."""
    assert PLUGIN_ROOT.startswith("${") and PLUGIN_ROOT.endswith("}"), PLUGIN_ROOT  # noqa: S101 -- build-time constant, not request input
    root = f"{PLUGIN_ROOT[:-1]}:-}}"
    adapter = f'"$r/{_SCRIPTS_TEMPLATE.format(name="vscode_copilot.py")}"'
    launcher = launch.plugin_interpreter(f"$r/{_SCRIPTS_TEMPLATE.format(name=launch.PLUGIN_LAUNCHER)}")
    named = f'"$r/{_SCRIPTS_TEMPLATE.format(name=target)}"'
    refuse = f"{{ echo '{_NO_ADAPTER_REFUSAL}' >&2; exit 2; }}"
    return f'r="{root}"; [ -n "$r" ] || exit 0; [ -f {adapter} ] || {refuse}; exec {launcher} {adapter} {flag} {named}'


def _hook_command(script: str) -> str:
    """The guard's invocation."""
    return _root_guarded(script, "--guard")


POSTURE_GATE_COPILOT = gate_package.gate_posture(
    "vscode_copilot",
    "Enforces only in a client that reads the com.github.copilot namespace and tells the hook where the package lives; a client that exports no plugin-root variable (VS Code's agent-plugin format exports none) runs the hook, which then exits 0 and checks nothing; a root that is set but lacks the bundled hook exits 2 and refuses the call.",
)


def _gate_command() -> str:
    """The same adapter, handed the packaged gate instead of a guard."""
    return _root_guarded("gate.json", "--gate")


def manifest_posture(*, enforced: bool, gate: bool = False) -> str:
    """The posture sentence a package's description ends with."""
    return (POSTURE_GATE_COPILOT if gate else POSTURE_ENFORCED_COPILOT) if enforced else POSTURE_ADVISORY


def build_copilot_manifest(
    manifest: dict[str, Any], policy_dir: Path, *, enforced: bool, gate: bool = False
) -> dict[str, Any]:
    """Derive the root `plugin.json` from a policy manifest."""
    data = build_manifest(manifest, policy_dir)
    posture = manifest_posture(enforced=enforced, gate=gate)
    data["description"] = f"{data['description']} [{posture}]".strip()
    extension = data["extensions"][NAMESPACE]
    del extension["manifest"]
    if enforced:
        del extension["coverage_without_chock"]
        extension["hooks"] = HOOKS_REL
    return data


def copilot_plugin_files(policy_dir: Path, manifest: dict[str, Any], repo_root: Path) -> dict[Path, str]:
    """The Copilot plugin's files as {relative path: content}, writing nothing."""
    policy_dir = Path(policy_dir)
    policy_id = manifest.get("id") or policy_dir.name
    name = plugin_name(str(policy_id))
    script = _guard_script(policy_dir, str(policy_id))
    gate = (
        None
        if script or not gate_package.gate_reaches("vscode_copilot")
        else tool_use_gate_spec(policy_dir, Path(repo_root))
    )
    enforced = script is not None or gate is not None

    skill = build_skill(policy_dir, manifest, Path(repo_root), hooks=HOOKS_REL if enforced else None)
    generic = advisory_note(policy_dir, manifest)
    if script:
        skill = skill.replace(generic, _COPILOT_ENFORCED_NOTE)
    elif gate:
        skill = skill.replace(generic, gate_package.gate_skill_note("vscode_copilot", gate.get("action")))

    files: dict[Path, str] = {
        Path(_LAYOUT["manifest"]): json.dumps(
            build_copilot_manifest(manifest, policy_dir, enforced=enforced, gate=gate is not None), indent=2
        )
        + "\n",
        Path(packaging.supports("copilot", packaging.SKILL).format(name=name)): skill,
    }
    for rel, content in skill_assets(policy_dir).items():
        files[Path(packaging.supports("copilot", packaging.SKILL).format(name=name)).parent / rel] = content
    licence = license_text(manifest)
    if licence:
        files[LICENSE_REL] = licence
    if script:
        files[Path(HOOKS_REL)] = json.dumps(hooks_map_file("vscode_copilot", _hook_command(script)), indent=2) + "\n"
        files.update(_runtime_files("vscode_copilot"))
        files.update(store.guard_files(policy_dir, script))
    elif gate:
        files[Path(HOOKS_REL)] = (
            json.dumps(gate_package.gate_hooks_file("vscode_copilot", _gate_command()), indent=2) + "\n"
        )
        files.update(_runtime_files("vscode_copilot"))
        files.update(gate_package.packaged_gate_files(policy_dir, gate, _SCRIPTS_TEMPLATE))
    return files


def stale_copilot_files(policy_dir: Path, manifest: dict[str, Any], repo_root: Path, out_dir: Path) -> list[Path]:
    """Files under this package that the current manifest would no longer produce."""
    return store.stale_store_files("copilot", copilot_plugin_files, policy_dir, manifest, repo_root, out_dir)


def build_copilot_plugin(policy_dir: Path, manifest: dict[str, Any], repo_root: Path, out_dir: Path) -> list[Path]:
    """Write the Copilot-format package for one policy into a distribution directory."""
    return store.build_store_plugin("copilot", copilot_plugin_files, policy_dir, manifest, repo_root, out_dir)


def copilot_plugin_differences(policy_dir: Path, manifest: dict[str, Any], repo_root: Path, out_dir: Path) -> list[str]:
    """Report where the on-disk Copilot plugin disagrees with what the manifest would produce."""
    return store.store_plugin_differences("copilot", copilot_plugin_files, policy_dir, manifest, repo_root, out_dir)
