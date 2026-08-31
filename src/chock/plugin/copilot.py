"""Emit a GitHub Copilot (Agent Plugins 1.0 + hooks) plugin from a policy directory."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agentseam import packaging

from chock.compile.emitters.claude_pretooluse import MATCHER, TIMEOUT_SECONDS, _guard_script
from chock.emit import write_generated
from chock.plugin.build import (
    _ADVISORY_NOTE_HOOK,
    _ADVISORY_NOTE_RULE,
    NAMESPACE,
    build_manifest,
    build_skill,
    plugin_name,
)
from chock.plugin.claude import POSTURE_ADVISORY, _adapter_source

_LAYOUT = packaging.layout("copilot")
PLUGIN_ROOT = packaging.plugin_root("copilot")
COPILOT_NAMESPACE = "com.github.copilot"
HOOKS_REL = packaging.supports("copilot", packaging.HOOKS)
_SCRIPTS_TEMPLATE = packaging.supports("copilot", packaging.EXECUTABLE)

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
    "This package ships a PreToolUse hook under com.github.copilot/ that enforces this "
    "policy in clients reading that namespace (documented for VS Code agent mode), subject "
    "to the fail posture stated in the plugin description. A client that ignores the "
    "namespace gets this text only. Repo-wide enforcement across every commit and in CI "
    "still needs `chock sync`. See https://github.com/open-coder-ai/chock"
)


def _hook_command(script: str) -> str:
    """One interpreter invocation against the plugin's own bundled copies."""
    adapter = packaging.executable_ref("copilot", _SCRIPTS_TEMPLATE.format(name="vscode_copilot.py"))
    guard = packaging.executable_ref("copilot", _SCRIPTS_TEMPLATE.format(name=script))
    return f'python3 "{adapter}" --guard "{guard}"'


def build_copilot_manifest(manifest: dict[str, Any], policy_dir: Path, enforced: bool) -> dict[str, Any]:
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
    if script:
        hooks = {
            "hooks": {
                "PreToolUse": [
                    {
                        "matcher": MATCHER,
                        "hooks": [{"type": "command", "command": _hook_command(script), "timeout": TIMEOUT_SECONDS}],
                    }
                ]
            }
        }
        files[Path(HOOKS_REL)] = json.dumps(hooks, indent=2) + "\n"
        files[Path(_SCRIPTS_TEMPLATE.format(name="vscode_copilot.py"))] = _adapter_source("vscode_copilot")
        files[Path(_SCRIPTS_TEMPLATE.format(name=script))] = (policy_dir / "implementations" / script).read_text(
            encoding="utf-8"
        )
    return files


OWNED_SUBTREES = (COPILOT_NAMESPACE, "scripts")


def stale_copilot_files(policy_dir: Path, manifest: dict[str, Any], repo_root: Path, out_dir: Path) -> list[Path]:
    """Files under this package that the current manifest would no longer produce."""
    out_dir = Path(out_dir)
    if not out_dir.is_dir():
        return []
    expected = set(copilot_plugin_files(Path(policy_dir), manifest, Path(repo_root)))
    stale: list[Path] = []
    for sub in OWNED_SUBTREES:
        for path in sorted((out_dir / sub).rglob("*")) if (out_dir / sub).is_dir() else []:
            if path.is_file() and path.relative_to(out_dir) not in expected:
                stale.append(path)
    return stale


def build_copilot_plugin(policy_dir: Path, manifest: dict[str, Any], repo_root: Path, out_dir: Path) -> list[Path]:
    """Write the Copilot-format package for one policy into a distribution directory."""
    written: list[Path] = []
    for rel, content in copilot_plugin_files(Path(policy_dir), manifest, Path(repo_root)).items():
        dest = Path(out_dir) / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        write_generated(dest, content)
        written.append(dest)

    for stale in stale_copilot_files(policy_dir, manifest, repo_root, out_dir):
        stale.unlink()
        parent = stale.parent
        while parent != Path(out_dir) and parent.is_dir() and not any(parent.iterdir()):
            parent.rmdir()
            parent = parent.parent
    return written


def copilot_plugin_differences(policy_dir: Path, manifest: dict[str, Any], repo_root: Path, out_dir: Path) -> list[str]:
    """Report where the on-disk Copilot plugin disagrees with what the manifest would produce."""
    policy_id = manifest.get("id") or Path(policy_dir).name
    differences: list[str] = []
    for rel, content in copilot_plugin_files(Path(policy_dir), manifest, Path(repo_root)).items():
        dest = Path(out_dir) / rel
        if not dest.exists():
            differences.append(f"missing: {policy_id}/{rel.as_posix()}")
        elif dest.read_text(encoding="utf-8") != content:
            differences.append(f"differs: {policy_id}/{rel.as_posix()}")
    for stale in stale_copilot_files(policy_dir, manifest, repo_root, out_dir):
        differences.append(f"stale: {policy_id}/{Path(stale).relative_to(Path(out_dir)).as_posix()}")
    return differences
