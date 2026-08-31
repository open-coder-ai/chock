"""Emit an Agent Plugins 1.0.0 package from a policy directory."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from chock.compile.emitters.advisory import advisory_lines
from chock.emit import write_generated

SCHEMA_URL = "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json"

NAMESPACE = "io.github.open-coder-ai"

_NAME_PATTERN = re.compile(r"^(?!.*(?:--|\.\.))[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?$")
_NAME_MAX = 64

MANIFEST_KEYS = (
    "$schema",
    "name",
    "version",
    "description",
    "author",
    "homepage",
    "repository",
    "license",
    "keywords",
    "extensions",
)


class PluginNameError(ValueError):
    """A policy id that cannot be a conformant plugin name."""


def plugin_name(policy_id: str) -> str:
    """Validate a policy id as an Agent Plugins `name`."""
    if len(policy_id) > _NAME_MAX or not _NAME_PATTERN.match(policy_id):
        raise PluginNameError(
            f"policy id {policy_id!r} is not a valid Agent Plugins name: "
            f"lowercase alphanumerics, dots and hyphens, no leading/trailing separator, "
            f"no '--' or '..', max {_NAME_MAX} chars"
        )
    return policy_id


def _one_line(text: Any) -> str:
    """Collapse a folded YAML block to a single line."""
    return " ".join(str(text or "").split())


def _keywords(manifest: dict[str, Any]) -> list[str]:
    """Discovery terms drawn from the manifest, never invented."""
    words = ["chock", "policy-as-code"]
    for key in ("artifact", "enforcement"):
        value = manifest.get(key)
        if value:
            words.append(str(value))
    for tag in (manifest.get("compliance") or {}).get("owasp_asi") or []:
        words.append(str(tag).lower())
    seen: set[str] = set()
    return [w for w in words if not (w in seen or seen.add(w))]


def _author(provenance: dict[str, Any]) -> dict[str, str] | None:
    """`author` is an object with `additionalProperties: false`, so only name/email/url."""
    name = _one_line(provenance.get("author"))
    return {"name": name} if name else None


def build_manifest(manifest: dict[str, Any], policy_dir: Path) -> dict[str, Any]:
    """Derive a conformant `plugin.json` from a policy manifest."""
    policy_id = manifest.get("id") or Path(policy_dir).name
    provenance = manifest.get("provenance") or {}

    data: dict[str, Any] = {
        "$schema": SCHEMA_URL,
        "name": plugin_name(str(policy_id)),
        "description": _one_line(manifest.get("description")),
        "keywords": _keywords(manifest),
        "extensions": {
            NAMESPACE: {
                "manifest": "manifest.yaml",
                "artifact": manifest.get("artifact"),
                "enforcement": manifest.get("enforcement"),
                "coverage_without_chock": "advisory",
            }
        },
    }
    if manifest.get("version"):
        data["version"] = str(manifest["version"])
    if provenance.get("license"):
        data["license"] = str(provenance["license"])
    if provenance.get("source_repo"):
        data["repository"] = str(provenance["source_repo"])
    author = _author(provenance)
    if author:
        data["author"] = author

    return {key: data[key] for key in MANIFEST_KEYS if key in data}


_ADVISORY_NOTE_HOOK = (
    "This skill is advisory: the client reading it has no mechanism to enforce it. "
    "The same policy compiled by `chock` becomes a git hook that exits non-zero. "
    "See https://github.com/open-coder-ai/chock"
)
_ADVISORY_NOTE_RULE = (
    "This skill is advisory: the client reading it has no mechanism to enforce it, and this "
    "policy stays advisory even when compiled by `chock` -- it ships rule text, not a blocking "
    "hook. See https://github.com/open-coder-ai/chock"
)


def build_skill(policy_dir: Path, manifest: dict[str, Any], repo_root: Path, hooks: str | None = None) -> str:
    """Render `SKILL.md` for a policy."""
    policy_id = manifest.get("id") or Path(policy_dir).name
    description = _one_line(manifest.get("description")) or f"Chock policy {policy_id}"

    lines = advisory_lines(Path(policy_dir), manifest, Path(repo_root))
    body = "\n".join(lines) if lines else f"see .agents/policies/{policy_id}/"

    coverage_line = f"  chock.hooks: {hooks}\n" if hooks else "  chock.coverage_without_chock: advisory\n"
    advisory_note = _ADVISORY_NOTE_HOOK if (manifest.get("artifact") == "hook") else _ADVISORY_NOTE_RULE
    return (
        "---\n"
        f"name: {policy_id}\n"
        f"description: {json.dumps(description)}\n"
        "metadata:\n"
        f"  chock.artifact: {manifest.get('artifact') or 'rule'}\n"
        f"  chock.enforcement: {manifest.get('enforcement') or 'advise'}\n"
        f"{coverage_line}"
        "---\n"
        "\n"
        f"# {manifest.get('name') or policy_id}\n"
        "\n"
        f"{description}\n"
        "\n"
        "```\n"
        f"{body}\n"
        "```\n"
        "\n"
        f"{advisory_note}\n"
    )


def plugin_files(policy_dir: Path, manifest: dict[str, Any], repo_root: Path) -> dict[Path, str]:
    """Return the plugin's files as {relative path: content}, writing nothing."""
    policy_id = manifest.get("id") or Path(policy_dir).name
    name = plugin_name(str(policy_id))
    return {
        Path("plugin.json"): json.dumps(build_manifest(manifest, policy_dir), indent=2) + "\n",
        Path("skills") / name / "SKILL.md": build_skill(policy_dir, manifest, repo_root),
    }


def build_plugin(
    policy_dir: Path, manifest: dict[str, Any], repo_root: Path, out_dir: Path | None = None
) -> list[Path]:
    """Write the Agent Plugins package for one policy. Defaults to in place."""
    target = Path(out_dir) if out_dir else Path(policy_dir)
    written: list[Path] = []
    for rel, content in plugin_files(Path(policy_dir), manifest, Path(repo_root)).items():
        dest = target / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        write_generated(dest, content)
        written.append(dest)
    return written


def plugin_differences(
    policy_dir: Path, manifest: dict[str, Any], repo_root: Path, target: Path | None = None
) -> list[str]:
    """Report where the on-disk plugin disagrees with what the manifest would produce."""
    policy_id = manifest.get("id") or Path(policy_dir).name
    differences: list[str] = []
    for rel, content in plugin_files(Path(policy_dir), manifest, Path(repo_root)).items():
        dest = Path(target if target is not None else policy_dir) / rel
        if not dest.exists():
            differences.append(f"missing: {policy_id}/{rel.as_posix()}")
        elif dest.read_text(encoding="utf-8") != content:
            differences.append(f"differs: {policy_id}/{rel.as_posix()}")
    return differences
