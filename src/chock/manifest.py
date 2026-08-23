"""Manifest filename resolution and SKILL.md frontmatter projection."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

# The frontmatter metadata codec lives in skill_metadata.py: the flat-string dialect
# (dotted keys, comma-joined lists, "true"/"false" booleans) is decoded in one place.
from chock.skill_metadata import _as_bool, _as_list, _chock_metadata

CANONICAL_MANIFEST = "manifest.yaml"
MANIFEST_NAMES: tuple[str, ...] = (CANONICAL_MANIFEST,)
SKILL_MD = "SKILL.md"
INTERFACE_YAML = "interface.yaml"


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
    """Load the optional interface.yaml next to a SKILL.md. Returns empty if absent.

    Malformed or unreadable interface.yaml is reported as a warning and ignored.
    """
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

    # identity: id from metadata.chock.id, else frontmatter.name, else folder name
    front_name = frontmatter.get("name", artifact_dir.name)
    if not isinstance(front_name, str):
        front_name = str(front_name)

    if front_name != artifact_dir.name:
        if warnings is not None:
            warnings.append(f"frontmatter name '{front_name}' does not match directory name '{artifact_dir.name}'")

    if len(front_name) > 128:
        if warnings is not None:
            warnings.append(f"name exceeds 128 characters ({len(front_name)})")

    data["id"] = ac.get("id") or artifact_dir.name
    data["name"] = ac.get("name") or front_name
    data["description"] = frontmatter["description"]

    # core fields with safe defaults for third-party skills
    _set_or_default(data, "version", ac.get("version"), "0.0.0", warnings)
    _set_or_default(data, "artifact", ac.get("artifact"), "skill", warnings)
    _set_or_default(data, "enforcement", ac.get("enforcement"), "advise", warnings)

    # provenance: unknown provenance lands in sandbox with a generic license
    provenance = ac.get("provenance") or {}
    _set_or_default(data, "provenance.author", provenance.get("author"), "unknown", warnings)
    _set_or_default(data, "provenance.source_repo", provenance.get("source_repo"), "unknown", warnings)
    _set_or_default(data, "provenance.license", provenance.get("license"), "proprietary", warnings)
    _set_or_default(data, "provenance.trust_tier", provenance.get("trust_tier"), "sandbox", warnings)

    # lifecycle
    lifecycle = ac.get("lifecycle") or {}
    _set_or_default(data, "lifecycle.status", lifecycle.get("status"), "draft", warnings)

    # security: required by check_security_baseline, default for unknown skills
    security = ac.get("security") or {}
    _set_or_default(data, "security.content_instructions", security.get("content_instructions"), "never-obey", warnings)

    # skill payload
    skill_type = ac.get("skill_type")
    _set_or_default(data, "skill.skill_type", skill_type, "nl", warnings)
    data["skill"]["entry"] = manifest_path.name
    _set_or_default(data, "skill.effects", _as_list(ac.get("effects")), ["none"], warnings)

    if "approval" in ac:
        data["skill"]["approval"] = ac["approval"]

    # carry forward any explicitly-declared blocks
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
            # The two boolean carriers arrive as "true"/"false" strings in the
            # flat-string metadata dialect; everything else passes through as-is.
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
    """Return the manifest path for a directory, or None if absent.

    Resolution order is manifest.yaml -> SKILL.md, checking direct children only.
    Callers that need to detect ambiguity must use load_manifest(), which checks
    whether the sibling file is also present.
    """
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

    # Find the end of the first YAML document: next '---' or '...' on its own line.
    end = -1
    for i in range(1, len(lines)):
        if lines[i].strip() in {"---", "..."}:
            end = i
            break

    if end == -1:
        return {}

    try:
        return yaml.safe_load("\n".join(lines[:end])) or {}
    except yaml.YAMLError:
        raise


def normalize_manifest(data: dict[str, Any]) -> dict[str, Any]:
    """Apply v3 manifest defaults that JSON Schema cannot enforce.

    This mutates `data` in place before schema validation and registry indexing,
    so `validate`, `compile`, and the registry all inspect the same resolved dict.
    A future rule such as "propagation must be explicit on block policies" would
    therefore see the defaulted value, not the raw file.

    propagation defaults to 'inherit' when absent, enforcement is present, and
    enforcement is not 'advise'.
    """
    if "propagation" not in data and data.get("enforcement") is not None and data.get("enforcement") != "advise":
        data["propagation"] = "inherit"
    return data


def load_manifest_file(
    manifest_path: Path,
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    """Parse and normalize a manifest by file path.

    Handles manifest.yaml and SKILL.md frontmatter. Raises yaml.YAMLError on
    malformed YAML, OSError on unreadable files, and ManifestSourceError when a
    SKILL.md frontmatter is missing required fields.
    """
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

    # Direct-children-only ambiguity check.
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
