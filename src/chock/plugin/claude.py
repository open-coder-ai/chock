"""Emit a Claude-format plugin from a policy directory."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agentseam import packaging

from chock.compile.emitters.claude_pretooluse import MATCHER, TIMEOUT_SECONDS, _guard_script
from chock.emit import write_generated
from chock.gate import runtime_bundle
from chock.plugin.build import (
    _ADVISORY_NOTE_HOOK,
    _ADVISORY_NOTE_RULE,
    _author,
    _keywords,
    _one_line,
    build_skill,
    plugin_name,
)

_MANIFEST_REL = packaging.layout("claude_code")["manifest"]
_SCRIPTS_TEMPLATE = packaging.supports("claude_code", packaging.EXECUTABLE)

POSTURE_ENFORCED = (
    "Session-enforced via a PreToolUse hook; needs python3 and a usable bash. Without them, "
    "fail-open clients allow silently; fail-closed clients refuse matched commands. On Windows, "
    "disable the python3 Store alias or install Python. If the guard itself crashes or times "
    "out, the hook asks for confirmation rather than allowing silently."
)
POSTURE_ADVISORY = "Advisory skill only; enforcement needs chock installed in the repo."

_ENFORCED_NOTE = (
    "This policy is enforced in this client by a PreToolUse hook installed with the plugin, "
    "subject to the fail conditions stated in the plugin description. Repo-wide "
    "enforcement across every commit and in CI still needs `chock sync`. "
    "See https://github.com/open-coder-ai/chock"
)


def _adapter_source(agent: str = "claude_code") -> str:
    """`agent`'s self-contained runtime, verbatim -- agentseam's bundle plus chock's own"""
    return runtime_bundle.render(agent)


def _hook_command(script: str) -> str:
    """One interpreter invocation, deliberately without a fallback chain."""
    adapter = packaging.executable_ref("claude_code", _SCRIPTS_TEMPLATE.format(name="claude_code.py"))
    guard = packaging.executable_ref("claude_code", _SCRIPTS_TEMPLATE.format(name=script))
    return f'python3 "{adapter}" --guard "{guard}"'


def build_claude_manifest(manifest: dict[str, Any], policy_dir: Path, enforced: bool) -> dict[str, Any]:
    """Derive `.claude-plugin/plugin.json` from a policy manifest."""
    policy_id = manifest.get("id") or Path(policy_dir).name
    provenance = manifest.get("provenance") or {}
    posture = POSTURE_ENFORCED if enforced else POSTURE_ADVISORY

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

    skill = build_skill(policy_dir, manifest, Path(repo_root), hooks="hooks/hooks.json" if script else None)
    if script:
        skill = skill.replace(_ADVISORY_NOTE_RULE, _ENFORCED_NOTE).replace(_ADVISORY_NOTE_HOOK, _ENFORCED_NOTE)

    files: dict[Path, str] = {
        Path(_MANIFEST_REL): json.dumps(
            build_claude_manifest(manifest, policy_dir, enforced=script is not None), indent=2
        )
        + "\n",
        Path(packaging.supports("claude_code", packaging.SKILL).format(name=name)): skill,
    }
    if script:
        hooks_rel = packaging.supports("claude_code", packaging.HOOKS)
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
        files[Path(hooks_rel)] = json.dumps(hooks, indent=2) + "\n"
        files[Path(_SCRIPTS_TEMPLATE.format(name="claude_code.py"))] = _adapter_source("claude_code")
        files[Path(_SCRIPTS_TEMPLATE.format(name=script))] = (policy_dir / "implementations" / script).read_text(
            encoding="utf-8"
        )
    return files


OWNED_SUBTREES = ("hooks", "scripts")


def stale_claude_files(policy_dir: Path, manifest: dict[str, Any], repo_root: Path, out_dir: Path) -> list[Path]:
    """Files under this package that the current manifest would no longer produce."""
    out_dir = Path(out_dir)
    if not out_dir.is_dir():
        return []
    expected = set(claude_plugin_files(Path(policy_dir), manifest, Path(repo_root)))
    stale: list[Path] = []
    for sub in OWNED_SUBTREES:
        for path in sorted((out_dir / sub).rglob("*")) if (out_dir / sub).is_dir() else []:
            if path.is_file() and path.relative_to(out_dir) not in expected:
                stale.append(path)
    return stale


def build_claude_plugin(policy_dir: Path, manifest: dict[str, Any], repo_root: Path, out_dir: Path) -> list[Path]:
    """Write the Claude-format package for one policy into a distribution directory."""
    written: list[Path] = []
    for rel, content in claude_plugin_files(Path(policy_dir), manifest, Path(repo_root)).items():
        dest = Path(out_dir) / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        write_generated(dest, content)
        written.append(dest)

    for stale in stale_claude_files(policy_dir, manifest, repo_root, out_dir):
        stale.unlink()
        parent = stale.parent
        while parent != Path(out_dir) and parent.is_dir() and not any(parent.iterdir()):
            parent.rmdir()
            parent = parent.parent
    return written


def claude_plugin_differences(policy_dir: Path, manifest: dict[str, Any], repo_root: Path, out_dir: Path) -> list[str]:
    """Report where the on-disk Claude plugin disagrees with what the manifest would produce."""
    policy_id = manifest.get("id") or Path(policy_dir).name
    differences: list[str] = []
    for rel, content in claude_plugin_files(Path(policy_dir), manifest, Path(repo_root)).items():
        dest = Path(out_dir) / rel
        if not dest.exists():
            differences.append(f"missing: {policy_id}/{rel.as_posix()}")
        elif dest.read_text(encoding="utf-8") != content:
            differences.append(f"differs: {policy_id}/{rel.as_posix()}")
    for stale in stale_claude_files(policy_dir, manifest, repo_root, out_dir):
        differences.append(f"stale: {policy_id}/{Path(stale).relative_to(Path(out_dir)).as_posix()}")
    return differences
