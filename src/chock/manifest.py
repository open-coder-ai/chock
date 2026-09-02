"""Manifest filename resolution and SKILL.md frontmatter projection."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from chock.skill_metadata import _as_bool, _as_list, _chock_metadata

CANONICAL_MANIFEST = "manifest.yaml"
MANIFEST_NAMES: tuple[str, ...] = (CANONICAL_MANIFEST,)
SKILL_MD = "SKILL.md"
INTERFACE_YAML = "interface.yaml"

#: Longest a manifest/frontmatter `name` may be before it's flagged.
_MAX_NAME_LENGTH = 128


class ManifestSourceError(Exception):
    """A manifest directory has an ambiguous or incomplete source of truth."""


def _set_or_default(
    data: dict[str, Any],
    dotted_path: str,
    source: Any,
    default: Any,
    warnings: list[str] | None,
) -> None:
    """Set a nested value, warning only when the default was used."""
    keys = dotted_path.split(".")
    node = data
    for key in keys[:-1]:
        if key not in node or not isinstance(node[key], dict):
            node[key] = {}
        node = node[key]
    leaf = keys[-1]
    if source is not None:
        node[leaf] = source
        return
    node[leaf] = default
    if warnings is not None:
        warnings.append(f"defaulted {dotted_path} to {default!r}")


def _load_interface(
    artifact_dir: Path,
    warnings: list[str] | None,
) -> dict[str, Any]:
    """Load the optional interface.yaml next to a SKILL.md. Returns empty if absent."""
    interface_path = artifact_dir / INTERFACE_YAML
    if not interface_path.exists():
        return {}

    try:
        data = yaml.safe_load(interface_path.read_text(encoding="utf-8")) or {}
    except (yaml.YAMLError, OSError) as exc:
        if warnings is not None:
            warnings.append(f"interface.yaml parse error: {exc}")
        return {}

    return data if isinstance(data, dict) else {}


def _project_skill_frontmatter(
    manifest_path: Path,
    frontmatter: dict[str, Any],
    warnings: list[str] | None,
) -> dict[str, Any]:
    """Turn a SKILL.md frontmatter document into a v3 manifest dict."""
    artifact_dir = manifest_path.parent
    ac = _chock_metadata(frontmatter)

    if "description" not in frontmatter or frontmatter["description"] is None:
        raise ManifestSourceError("description is a required frontmatter field")

    data: dict[str, Any] = {}

    front_name = frontmatter.get("name", artifact_dir.name)
    if not isinstance(front_name, str):
        front_name = str(front_name)

    if front_name != artifact_dir.name and warnings is not None:
        warnings.append(f"frontmatter name '{front_name}' does not match directory name '{artifact_dir.name}'")

    if len(front_name) > _MAX_NAME_LENGTH and warnings is not None:
        warnings.append(f"name exceeds 128 characters ({len(front_name)})")

    data["id"] = ac.get("id") or artifact_dir.name
    data["name"] = ac.get("name") or front_name
    data["description"] = frontmatter["description"]

    _set_or_default(data, "version", ac.get("version"), "0.0.0", warnings)
    _set_or_default(data, "artifact", ac.get("artifact"), "skill", warnings)
    _set_or_default(data, "enforcement", ac.get("enforcement"), "advise", warnings)

    provenance = ac.get("provenance") or {}
    _set_or_default(data, "provenance.author", provenance.get("author"), "unknown", warnings)
    _set_or_default(data, "provenance.source_repo", provenance.get("source_repo"), "unknown", warnings)
    _set_or_default(data, "provenance.license", provenance.get("license"), "proprietary", warnings)
    _set_or_default(data, "provenance.trust_tier", provenance.get("trust_tier"), "sandbox", warnings)

    lifecycle = ac.get("lifecycle") or {}
    _set_or_default(data, "lifecycle.status", lifecycle.get("status"), "draft", warnings)

    security = ac.get("security") or {}
    _set_or_default(data, "security.content_instructions", security.get("content_instructions"), "never-obey", warnings)

    skill_type = ac.get("skill_type")
    _set_or_default(data, "skill.skill_type", skill_type, "nl", warnings)
    data["skill"]["entry"] = manifest_path.name
    _set_or_default(data, "skill.effects", _as_list(ac.get("effects")), ["none"], warnings)

    if "approval" in ac:
        data["skill"]["approval"] = ac["approval"]

    for key in [
        "applies_to",
        "optimization",
        "validation",
        "concerns",
        "conflicts_with",
        "bundle",
        "categories",
        "determinization_reviewed",
        "scripts",
        "compliance",
        "agent_specific_vocabulary",
    ]:
        if key in ac:
            if key in ("determinization_reviewed", "agent_specific_vocabulary"):
                data[key] = _as_bool(ac[key])
            else:
                data[key] = ac[key]

    if "input_schema" in ac:
        data["input_schema"] = ac["input_schema"]
    if "output_schema" in ac:
        data["output_schema"] = ac["output_schema"]
    if "evaluation" in ac:
        data["evaluation"] = ac["evaluation"]
    if "composition" in ac:
        data["composition"] = ac["composition"]
    if "dependencies" in ac:
        data["dependencies"] = ac["dependencies"]
    if "tags" in ac:
        data["tags"] = ac["tags"]
    if "changelog" in ac:
        data["changelog"] = ac["changelog"]

    return normalize_manifest(data)


def resolve_manifest_path(artifact_dir: Path) -> Path | None:
    """Return the manifest path for a directory, or None if absent."""
    candidate = Path(artifact_dir) / CANONICAL_MANIFEST
    if candidate.exists():
        return candidate
    candidate = Path(artifact_dir) / SKILL_MD
    if candidate.exists():
        return candidate
    return None


def _parse_skill_frontmatter(text: str) -> dict[str, Any]:
    """Parse the YAML frontmatter from a SKILL.md body."""
    if not text.startswith("---"):
        return {}

    lines = text.splitlines()
    if not lines:
        return {}

    end = -1
    for i in range(1, len(lines)):
        if lines[i].strip() in {"---", "..."}:
            end = i
            break

    if end == -1:
        return {}

    return yaml.safe_load("\n".join(lines[:end])) or {}


def normalize_manifest(data: dict[str, Any]) -> dict[str, Any]:
    """Apply v3 manifest defaults that JSON Schema cannot enforce."""
    if "propagation" not in data and data.get("enforcement") is not None and data.get("enforcement") != "advise":
        data["propagation"] = "inherit"
    return data


def load_manifest_file(
    manifest_path: Path,
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    """Parse and normalize a manifest by file path."""
    text = manifest_path.read_text(encoding="utf-8")

    if manifest_path.name == SKILL_MD:
        frontmatter = _parse_skill_frontmatter(text)
        return _project_skill_frontmatter(manifest_path, frontmatter, warnings)

    data = yaml.safe_load(text) or {}
    return normalize_manifest(data)


def load_manifest(
    artifact_dir: Path,
    warnings: list[str] | None = None,
) -> tuple[dict[str, Any], Path] | None:
    """Resolve a directory's manifest, then delegate to load_manifest_file."""
    path = resolve_manifest_path(artifact_dir)
    if path is None:
        return None

    has_manifest = (artifact_dir / CANONICAL_MANIFEST).exists()
    has_skill = (artifact_dir / SKILL_MD).exists()
    if has_manifest and has_skill:
        raise ManifestSourceError(f"both {CANONICAL_MANIFEST} and {SKILL_MD} are present; remove one")

    data = load_manifest_file(path, warnings)
    interface = _load_interface(artifact_dir, warnings)
    for key in ("input_schema", "output_schema", "evaluation"):
        if key in interface:
            data[key] = interface[key]

    return data, path
