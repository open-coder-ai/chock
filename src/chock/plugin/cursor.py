"""Emit a Cursor plugin (`.cursor-plugin/`) from a policy directory."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agentseam import packaging

from chock.compile.emitters.in_agent import _guard_script, cursor_hooks_file
from chock.plugin import posture, store
from chock.plugin.build import (
    _ADVISORY_NOTE_HOOK,
    _ADVISORY_NOTE_RULE,
    LICENSE_REL,
    _author,
    _keywords,
    _one_line,
    build_skill,
    license_text,
    plugin_name,
)
from chock.plugin.claude import POSTURE_ADVISORY, _adapter_source
from chock.plugin.store import SCRIPTS_TEMPLATE as _SCRIPTS_TEMPLATE

_LAYOUT = packaging.layout("cursor")
PLUGIN_ROOT = packaging.plugin_root("cursor")
HOOKS_REL = packaging.supports("cursor", packaging.HOOKS)
SKILLS_REL = _LAYOUT["declares"][packaging.SKILL][1]

MANIFEST_KEYS = (
    "name",
    "displayName",
    "description",
    "version",
    "author",
    "repository",
    "license",
    "keywords",
    "category",
    "skills",
    "hooks",
)

POSTURE_ENFORCED_CURSOR = posture.enforced_cursor()

_ENFORCED_NOTE_CURSOR = (
    "This policy is enforced in Cursor by the beforeShellExecution hook shipped with this "
    "plugin, subject to the fail conditions stated in the plugin description. "
    "Repo-wide enforcement across every commit and in CI still needs `chock sync`. "
    "See https://github.com/open-coder-ai/chock"
)


def _hook_command(script: str) -> str:
    """One interpreter invocation against the plugin's own bundled copies."""
    adapter = packaging.executable_ref("cursor", _SCRIPTS_TEMPLATE.format(name="cursor.py"))
    guard = packaging.executable_ref("cursor", _SCRIPTS_TEMPLATE.format(name=script))
    return f'python3 "{adapter}" --guard "{guard}"'


def build_cursor_manifest(manifest: dict[str, Any], policy_dir: Path, *, enforced: bool) -> dict[str, Any]:
    """Derive `.cursor-plugin/plugin.json` from a policy manifest."""
    policy_id = str(manifest.get("id") or Path(policy_dir).name)
    provenance = manifest.get("provenance") or {}
    posture = POSTURE_ENFORCED_CURSOR if enforced else POSTURE_ADVISORY

    data: dict[str, Any] = {
        "name": plugin_name(policy_id),
        "displayName": _one_line(manifest.get("name")) or policy_id,
        "description": f"{_one_line(manifest.get('description'))} [{posture}]".strip(),
        "keywords": _keywords(manifest),
        "category": "developer-tools",
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


def cursor_plugin_files(policy_dir: Path, manifest: dict[str, Any], repo_root: Path) -> dict[Path, str]:
    """The Cursor plugin's files as {relative path: content}, writing nothing."""
    policy_dir = Path(policy_dir)
    policy_id = str(manifest.get("id") or policy_dir.name)
    name = plugin_name(policy_id)
    script = _guard_script(policy_dir, policy_id)

    skill = build_skill(policy_dir, manifest, Path(repo_root), hooks=HOOKS_REL if script else None)
    if script:
        skill = skill.replace(_ADVISORY_NOTE_RULE, _ENFORCED_NOTE_CURSOR).replace(
            _ADVISORY_NOTE_HOOK, _ENFORCED_NOTE_CURSOR
        )

    files: dict[Path, str] = {
        Path(_LAYOUT["manifest"]): json.dumps(
            build_cursor_manifest(manifest, policy_dir, enforced=script is not None), indent=2
        )
        + "\n",
        Path(packaging.supports("cursor", packaging.SKILL).format(name=name)): skill,
    }
    licence = license_text(manifest)
    if licence:
        files[LICENSE_REL] = licence
    if script:
        files[Path(HOOKS_REL)] = json.dumps(cursor_hooks_file(_hook_command(script)), indent=2) + "\n"
        files[Path(_SCRIPTS_TEMPLATE.format(name="cursor.py"))] = _adapter_source("cursor")
        files[Path(_SCRIPTS_TEMPLATE.format(name=script))] = (policy_dir / "implementations" / script).read_text(
            encoding="utf-8"
        )
    return files


def stale_cursor_files(policy_dir: Path, manifest: dict[str, Any], repo_root: Path, out_dir: Path) -> list[Path]:
    """Files under this package that the current manifest would no longer produce."""
    return store.stale_store_files("cursor", cursor_plugin_files, policy_dir, manifest, repo_root, out_dir)


def build_cursor_plugin(policy_dir: Path, manifest: dict[str, Any], repo_root: Path, out_dir: Path) -> list[Path]:
    """Write the Cursor package for one policy into a distribution directory."""
    return store.build_store_plugin("cursor", cursor_plugin_files, policy_dir, manifest, repo_root, out_dir)


def cursor_plugin_differences(policy_dir: Path, manifest: dict[str, Any], repo_root: Path, out_dir: Path) -> list[str]:
    """Report where the on-disk Cursor plugin disagrees with what the manifest would produce."""
    return store.store_plugin_differences("cursor", cursor_plugin_files, policy_dir, manifest, repo_root, out_dir)
