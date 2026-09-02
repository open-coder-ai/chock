"""Emit a GitHub Copilot (Agent Plugins 1.0 + hooks) plugin from a policy directory."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agentseam import packaging

from chock.compile.emitters.in_agent import _guard_script, hooks_map_file
from chock.plugin import store
from chock.plugin.build import (
    _ADVISORY_NOTE_HOOK,
    _ADVISORY_NOTE_RULE,
    LICENSE_REL,
    NAMESPACE,
    build_manifest,
    build_skill,
    license_text,
    plugin_name,
)
from chock.plugin.claude import POSTURE_ADVISORY, _adapter_source
from chock.plugin.store import SCRIPTS_TEMPLATE as _SCRIPTS_TEMPLATE

_LAYOUT = packaging.layout("copilot")
PLUGIN_ROOT = packaging.plugin_root("copilot")
HOOKS_REL = packaging.supports("copilot", packaging.HOOKS)

POSTURE_ENFORCED_COPILOT = (
    "Session-enforced by the PreToolUse hook under com.github.copilot/ in clients that "
    "read that namespace (documented for VS Code agent mode); a client that ignores it, "
    "as the Agent Plugins spec tells generic clients to, gets the advisory skill only. "
    "The hook needs python3 and a usable bash. Without them, fail-open clients allow "
    "silently; fail-closed clients refuse matched commands. On Windows, disable the "
    "python3 Store alias or install Python. If the guard itself crashes or times out, the "
    "hook asks for confirmation rather than allowing silently -- VS Code agent mode honours "
    "that ask and it overrides the client's own auto-approve."
)

_COPILOT_ENFORCED_NOTE = (
    "This package ships a PreToolUse hook under com.github.copilot/. It enforces only in a "
    "client that both reads that namespace AND tells the hook where the package lives; a "
    "client that exports no plugin-root variable runs the hook, which then allows -- so "
    "treat this package as advisory unless a deny has been witnessed in your own client. "
    "A client that ignores the namespace gets this text only. Repo-wide enforcement across "
    "every commit and in CI still needs `chock sync`. "
    "See https://github.com/open-coder-ai/chock"
)


def _hook_command(script: str) -> str:
    """One interpreter invocation, guarded so an unresolved plugin root ALLOWS."""
    assert PLUGIN_ROOT.startswith("${") and PLUGIN_ROOT.endswith("}"), PLUGIN_ROOT
    root = f"{PLUGIN_ROOT[:-1]}:-}}"
    adapter = f'"$r/{_SCRIPTS_TEMPLATE.format(name="vscode_copilot.py")}"'
    guard = f'"$r/{_SCRIPTS_TEMPLATE.format(name=script)}"'
    return f'r="{root}"; [ -n "$r" ] && [ -f {adapter} ] || exit 0; exec python3 {adapter} --guard {guard}'


def build_copilot_manifest(manifest: dict[str, Any], policy_dir: Path, *, enforced: bool) -> dict[str, Any]:
    """Derive the root `plugin.json` from a policy manifest."""
    data = build_manifest(manifest, policy_dir)
    posture = POSTURE_ENFORCED_COPILOT if enforced else POSTURE_ADVISORY
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

    skill = build_skill(policy_dir, manifest, Path(repo_root), hooks=HOOKS_REL if script else None)
    if script:
        skill = skill.replace(_ADVISORY_NOTE_RULE, _COPILOT_ENFORCED_NOTE).replace(
            _ADVISORY_NOTE_HOOK, _COPILOT_ENFORCED_NOTE
        )

    files: dict[Path, str] = {
        Path(_LAYOUT["manifest"]): json.dumps(
            build_copilot_manifest(manifest, policy_dir, enforced=script is not None), indent=2
        )
        + "\n",
        Path(packaging.supports("copilot", packaging.SKILL).format(name=name)): skill,
    }
    licence = license_text(manifest)
    if licence:
        files[LICENSE_REL] = licence
    if script:
        files[Path(HOOKS_REL)] = json.dumps(hooks_map_file("vscode_copilot", _hook_command(script)), indent=2) + "\n"
        files[Path(_SCRIPTS_TEMPLATE.format(name="vscode_copilot.py"))] = _adapter_source("vscode_copilot")
        files[Path(_SCRIPTS_TEMPLATE.format(name=script))] = (policy_dir / "implementations" / script).read_text(
            encoding="utf-8"
        )
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
