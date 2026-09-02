"""Build a structured INDEX.md from installed policies."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from chock.compile.emitters.advisory import substitute_policy_vars, template_message
from chock.config import _disabled_list, load_config
from chock.gate.build import build_gate_json
from chock.manifest import ManifestSourceError, load_manifest

_ENFORCEMENT_ORDER = {"block": 0, "verify": 1, "advise": 2}


@dataclass
class IndexEntry:
    """One renderable row in INDEX.md."""

    id: str
    name: str
    artifact: str
    enforcement: str
    description: str
    rule_text: str = ""
    manifest_path: str = ""

    def priority(self) -> int:
        return _ENFORCEMENT_ORDER.get(self.enforcement, 3)

    def sort_key(self) -> tuple[int, str]:
        return (self.priority(), self.id)


def _default_id(artifact_dir: Path, manifest: dict[str, Any]) -> str:
    return manifest.get("id") or artifact_dir.name


def _load_policy(root: Path, artifact_dir: Path, warnings: list[str]) -> tuple[dict[str, Any], str] | None:
    """Return (manifest, manifest_relative_path) or None on any failure."""
    try:
        result = load_manifest(artifact_dir, warnings=warnings)
    except (yaml.YAMLError, OSError, ManifestSourceError) as exc:
        warnings.append(f"{artifact_dir}: manifest_parse: {exc}")
        return None
    if result is None:
        return None
    manifest, manifest_path = result
    rel_path = manifest_path.relative_to(root).as_posix()
    return manifest, rel_path


def _summarize_hook(manifest: dict[str, Any], artifact_dir: Path, root: Path) -> str:
    """One-line gate summary from a hook manifest, resolved against this repo's config."""
    gate = (manifest.get("hook") or {}).get("gate") or {}
    if gate.get("message"):
        spec = build_gate_json(artifact_dir, root)
        params = spec["params"] if spec else (gate.get("params") or {})
        message = template_message(str(gate["message"]), params)
        return message.splitlines()[0].strip()
    if manifest.get("description"):
        return str(manifest["description"]).splitlines()[0].strip()
    return "automatic gate"


def _one_liner(description: str) -> str:
    if not description:
        return ""
    return str(description).splitlines()[0].strip()


def _entry_from_manifest(artifact_dir: Path, manifest: dict[str, Any], rel_path: str, root: Path) -> IndexEntry:
    artifact = manifest.get("artifact") or "skill"
    pid = _default_id(artifact_dir, manifest)
    name = manifest.get("name") or pid
    enforcement = manifest.get("enforcement") or "advise"
    rule_text = substitute_policy_vars(str((manifest.get("rule") or {}).get("text", "")), artifact_dir)
    description = _one_liner(manifest.get("description", ""))

    if artifact == "hook":
        description = _summarize_hook(manifest, artifact_dir, root)

    return IndexEntry(
        id=pid,
        name=name,
        artifact=artifact,
        enforcement=enforcement,
        description=description,
        rule_text=rule_text,
        manifest_path=rel_path,
    )


def build_entries(root: Path) -> tuple[list[IndexEntry], list[str]]:
    """Return a list of active IndexEntry objects plus any manifest warnings."""
    # chock.validation.loading -> chock.validation (package) -> checks_repo -> this module (cycle).
    from chock.validation.loading import discover_artifacts  # noqa: PLC0415

    config = load_config(root)
    disabled = _disabled_list(config)
    entries: list[IndexEntry] = []
    warnings: list[str] = []

    for artifact_type, artifact_dir in discover_artifacts(root):
        if artifact_type == "eval":
            continue
        if not artifact_dir.is_dir():
            continue

        result = _load_policy(root, artifact_dir, warnings)
        if result is None:
            continue
        manifest, rel_path = result
        pid = _default_id(artifact_dir, manifest)
        if pid in disabled:
            continue

        entries.append(_entry_from_manifest(artifact_dir, manifest, rel_path, root))

    return entries, warnings


def max_tokens_for(root: Path, default: int = 2000) -> int:
    """Resolve config.yaml -> index.max_tokens, defaulting to 2000."""
    config = load_config(root)
    try:
        value = config.get("chock", {}).get("index", {}).get("max_tokens", default)
        return int(value)
    except (ValueError, TypeError):
        return default


def emit_warnings(warnings: list[str]) -> None:
    """Print collected manifest warnings to stderr."""
    for message in warnings:
        print(f"[WARN] {message}", file=sys.stderr)
