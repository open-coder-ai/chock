"""Emit an OpenAI Codex plugin (`.codex-plugin/`) from a policy directory."""

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
    _author,
    _keywords,
    _one_line,
    build_skill,
    plugin_name,
)
from chock.plugin.claude import POSTURE_ADVISORY, _adapter_source
from chock.plugin.listing import ICON_REL, LICENSE_REL, icon_svg, interface_block, license_text

_LAYOUT = packaging.layout("codex_cli")
PLUGIN_ROOT = packaging.plugin_root("codex_cli")
HOOKS_REL = packaging.supports("codex_cli", packaging.HOOKS)
SKILLS_REL = _LAYOUT["declares"][packaging.SKILL][1]
EVENT = "PreToolUse"

_SCRIPTS_TEMPLATE = "scripts/{name}"

MANIFEST_KEYS = (
    "name",
    "version",
    "description",
    "author",
    "repository",
    "license",
    "keywords",
    "interface",
    "skills",
    "hooks",
)

POSTURE_ENFORCED_CODEX = (
    "Session-enforced in Codex by a PreToolUse hook: a matched command is denied before "
    "it runs (witnessed blocking on Codex Desktop, Windows, 2026-08-24; the deny is "
    "returned as hook JSON, not an exit code, which Codex's Windows shell wrapper "
    "mangles). Codex requires a one-time trust review per hook -- the plugin is ADVISORY "
    "until you approve its hook, and a plugin update voids that trust until re-approved. "
    "The hook needs python3 on PATH; a failure of the HOOK (missing python3, a timeout, an "
    "unexpected exit) fails OPEN. A failure of the GUARD it runs is a DENY here, because "
    "Codex rejects the confirmation prompt the other clients get. Repo-wide enforcement "
    "at commit time and in CI still needs `chock sync`."
)

_ENFORCED_NOTE_CODEX = (
    "This policy is enforced in Codex by the PreToolUse hook shipped with this plugin, "
    "once its one-time trust review is approved (until then it is advisory, and a plugin "
    "update voids the trust until re-approved). Subject to the fail conditions in "
    "the plugin description. Repo-wide enforcement across every commit and in CI still "
    "needs `chock sync`. See https://github.com/open-coder-ai/chock"
)


def _hook_command(script: str) -> str:
    """One interpreter invocation against the plugin's own bundled copies."""
    adapter = packaging.executable_ref("codex_cli", _SCRIPTS_TEMPLATE.format(name="codex_cli.py"))
    guard = packaging.executable_ref("codex_cli", _SCRIPTS_TEMPLATE.format(name=script))
    return f'python3 "{adapter}" --guard "{guard}"'


def build_codex_manifest(manifest: dict[str, Any], policy_dir: Path, enforced: bool) -> dict[str, Any]:
    """Derive `.codex-plugin/plugin.json` from a policy manifest."""
    policy_id = str(manifest.get("id") or Path(policy_dir).name)
    provenance = manifest.get("provenance") or {}
    posture = POSTURE_ENFORCED_CODEX if enforced else POSTURE_ADVISORY

    description = _one_line(manifest.get("description"))

    data: dict[str, Any] = {
        "name": plugin_name(policy_id),
        "description": f"{description} [{posture}]".strip(),
        "keywords": _keywords(manifest),
        "interface": interface_block(manifest, policy_id, description),
        "skills": SKILLS_REL,
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
    if enforced:
        data["hooks"] = f"./{HOOKS_REL}"
    return {key: data[key] for key in MANIFEST_KEYS if key in data}


def codex_plugin_files(policy_dir: Path, manifest: dict[str, Any], repo_root: Path) -> dict[Path, str]:
    """The Codex plugin's files as {relative path: content}, writing nothing."""
    policy_dir = Path(policy_dir)
    policy_id = str(manifest.get("id") or policy_dir.name)
    name = plugin_name(policy_id)
    script = _guard_script(policy_dir, policy_id)

    skill = build_skill(policy_dir, manifest, Path(repo_root), hooks=HOOKS_REL if script else None)
    if script:
        skill = skill.replace(_ADVISORY_NOTE_RULE, _ENFORCED_NOTE_CODEX).replace(
            _ADVISORY_NOTE_HOOK, _ENFORCED_NOTE_CODEX
        )

    files: dict[Path, str] = {
        Path(_LAYOUT["manifest"]): json.dumps(
            build_codex_manifest(manifest, policy_dir, enforced=script is not None), indent=2
        )
        + "\n",
        Path(packaging.supports("codex_cli", packaging.SKILL).format(name=name)): skill,
        ICON_REL: icon_svg(),
    }
    licence = license_text(manifest)
    if licence:
        files[LICENSE_REL] = licence
    if script:
        hooks = {
            "hooks": {
                EVENT: [
                    {
                        "matcher": MATCHER,
                        "hooks": [{"type": "command", "command": _hook_command(script), "timeout": TIMEOUT_SECONDS}],
                    }
                ]
            },
        }
        files[Path(HOOKS_REL)] = json.dumps(hooks, indent=2) + "\n"
        files[Path(_SCRIPTS_TEMPLATE.format(name="codex_cli.py"))] = _adapter_source("codex_cli")
        files[Path(_SCRIPTS_TEMPLATE.format(name=script))] = (policy_dir / "implementations" / script).read_text(
            encoding="utf-8"
        )
    return files


OWNED_SUBTREES = ("hooks", "scripts", "assets")


def stale_codex_files(policy_dir: Path, manifest: dict[str, Any], repo_root: Path, out_dir: Path) -> list[Path]:
    """Files under this package that the current manifest would no longer produce."""
    out_dir = Path(out_dir)
    if not out_dir.is_dir():
        return []
    expected = set(codex_plugin_files(Path(policy_dir), manifest, Path(repo_root)))
    stale: list[Path] = []
    for sub in OWNED_SUBTREES:
        for path in sorted((out_dir / sub).rglob("*")) if (out_dir / sub).is_dir() else []:
            if path.is_file() and path.relative_to(out_dir) not in expected:
                stale.append(path)
    return stale


def build_codex_plugin(policy_dir: Path, manifest: dict[str, Any], repo_root: Path, out_dir: Path) -> list[Path]:
    """Write the Codex package for one policy into a distribution directory."""
    written: list[Path] = []
    for rel, content in codex_plugin_files(Path(policy_dir), manifest, Path(repo_root)).items():
        dest = Path(out_dir) / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        write_generated(dest, content)
        written.append(dest)
    for stale in stale_codex_files(policy_dir, manifest, repo_root, out_dir):
        stale.unlink()
        parent = stale.parent
        while parent != Path(out_dir) and parent.is_dir() and not any(parent.iterdir()):
            parent.rmdir()
            parent = parent.parent
    return written


def codex_plugin_differences(policy_dir: Path, manifest: dict[str, Any], repo_root: Path, out_dir: Path) -> list[str]:
    """Report where the on-disk Codex plugin disagrees with what the manifest would produce."""
    policy_id = manifest.get("id") or Path(policy_dir).name
    differences: list[str] = []
    for rel, content in codex_plugin_files(Path(policy_dir), manifest, Path(repo_root)).items():
        dest = Path(out_dir) / rel
        if not dest.exists():
            differences.append(f"missing: {policy_id}/{rel.as_posix()}")
        elif dest.read_text(encoding="utf-8") != content:
            differences.append(f"differs: {policy_id}/{rel.as_posix()}")
    for stale in stale_codex_files(policy_dir, manifest, repo_root, out_dir):
        differences.append(f"stale: {policy_id}/{Path(stale).relative_to(Path(out_dir)).as_posix()}")
    return differences
