"""Chock module (auto-organized from the original monolith)."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml

from chock.emit import write_generated_json
from chock.manifest import (
    ManifestSourceError,
    load_manifest,
    resolve_manifest_path,
)

REGISTRY_DIR = Path(".chock")

REGISTRY_FILE = REGISTRY_DIR / "registry.json"

REGISTRY_FORMAT_VERSION = "0.0.1"


@dataclass(frozen=True)
class SkippedManifest:
    path: Path
    reason: str


@dataclass
class RegistryEntry:
    id: str
    artifact: str
    version: str
    name: str
    description: str
    path: str
    manifest: str
    trust_tier: str
    lifecycle_status: str
    dependencies: list[str] = field(default_factory=list)
    script_hashes: dict[str, str] = field(default_factory=dict)


def repo_root() -> Path:
    return Path.cwd().resolve()


def registry_path(root: Path | None = None) -> Path:
    return (root or repo_root()) / REGISTRY_FILE


def ensure_registry_dir(root: Path | None = None) -> Path:
    path = (root or repo_root()) / REGISTRY_DIR
    path.mkdir(parents=True, exist_ok=True)
    return path


def discover_manifests(root: Path) -> list[tuple[str, Path]]:
    results: list[tuple[str, Path]] = []

    candidates = [
        (".agents/skills", "skill"),
        (".agents/policies", None),
        ("skills", "skill"),
        ("hooks", "hook"),
        ("rules", "rule"),
        ("subagents", "subagent"),
    ]

    def _append_entry(artifact_dir: Path, default_type: str | None) -> None:
        manifest = resolve_manifest_path(artifact_dir)
        if manifest is None:
            return

        art = default_type
        if art is None:
            try:
                data = yaml.safe_load(manifest.read_text(encoding="utf-8")) or {}
                art = data.get("artifact", "unknown")
            except (yaml.YAMLError, OSError):
                art = "unknown"
        results.append((art, manifest))

    def _add_subdirs(base: Path, default_type: str | None) -> None:
        for sub in base.iterdir():
            if sub.is_dir():
                _append_entry(sub, default_type)

    for rel_dir, default_type in candidates:
        base = root / rel_dir
        if not base.exists():
            continue

        if default_type == "subagent":
            for sub in base.iterdir():
                if not sub.is_dir():
                    continue
                manifest = sub / "subagent.yaml"
                if manifest.exists():
                    results.append(("subagent", manifest))
            continue

        _add_subdirs(base, default_type)

    return results


def _hash_file(path: Path) -> str:
    """Return sha256 hex digest of a file's contents."""
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def compute_script_hashes(artifact_dir: Path, manifest: dict[str, Any]) -> dict[str, str]:
    """Compute sha256 hashes for every deterministic script shipped with an artifact."""
    artifact = manifest.get("artifact", "")
    hashes: dict[str, str] = {}

    if artifact == "skill":
        scripts_dir = artifact_dir / "scripts"
        if scripts_dir.exists():
            for path in sorted(scripts_dir.rglob("*")):
                if path.is_file():
                    rel = path.relative_to(scripts_dir).as_posix()
                    hashes[rel] = _hash_file(path)
        return hashes

    if artifact == "hook":
        impl_dir = artifact_dir / "implementations"
        if impl_dir.exists():
            for path in sorted(impl_dir.rglob("*")):
                if path.is_file():
                    rel = path.relative_to(impl_dir).as_posix()
                    hashes[rel] = _hash_file(path)
        return hashes

    return hashes


def extract_dependencies(data: dict[str, Any], artifact: str) -> list[str]:
    deps: list[str] = []
    deps_data = data.get("dependencies", {})
    for dep in deps_data.get("skills", []):
        deps.append(dep.get("id"))

    return [d for d in deps if d]


def entry_from_manifest(
    artifact: str, manifest_path: Path, root: Path, warnings: list[str] | None = None
) -> RegistryEntry:
    artifact_dir = manifest_path.parent
    result = load_manifest(artifact_dir, warnings=warnings)
    if result is None:
        msg = f"no manifest in {artifact_dir}"
        raise ManifestSourceError(msg)
    data, resolved_path = result
    rel_path = resolved_path.parent.relative_to(root).as_posix()
    return RegistryEntry(
        id=data.get("id", ""),
        artifact=artifact,
        version=data.get("version", ""),
        name=data.get("name", ""),
        description=data.get("description", "").replace("\n", " ").strip(),
        path=rel_path,
        manifest=resolved_path.name,
        trust_tier=data.get("provenance", {}).get("trust_tier", "sandbox"),
        lifecycle_status=data.get("lifecycle", {}).get("status", "draft"),
        dependencies=extract_dependencies(data, artifact),
        script_hashes=compute_script_hashes(artifact_dir, data),
    )


def scan(
    root: Path | None = None,
) -> tuple[dict[str, list[RegistryEntry]], list[SkippedManifest]]:
    root = root or repo_root()
    entries: dict[str, list[RegistryEntry]] = {}
    skips: list[SkippedManifest] = []
    for artifact, manifest in discover_manifests(root):
        warnings: list[str] = []
        try:
            entry = entry_from_manifest(artifact, manifest, root, warnings=warnings)
        except (yaml.YAMLError, OSError, ManifestSourceError) as exc:
            skips.append(SkippedManifest(manifest, f"{type(exc).__name__}: {exc}"))
            continue
        for warning in warnings:
            print(f"[WARN] {entry.path} :: manifest_default: {warning}")
        entries.setdefault(entry.id, []).append(entry)
    return entries, skips


def save_registry(entries: dict[str, list[RegistryEntry]], root: Path | None = None) -> None:
    root = root or repo_root()
    ensure_registry_dir(root)
    data = {
        "version": REGISTRY_FORMAT_VERSION,
        "entries": {k: [asdict(e) for e in v] for k, v in sorted(entries.items())},
    }
    write_generated_json(registry_path(root), data)


def rescan_and_report(root: Path | None = None) -> None:
    """Rescan the artifact registry, print any manifest-parse skips, then persist it."""
    entries, skips = scan(root)
    if skips:
        print(f"[WARN] {len(skips)} manifest(s) skipped during registry scan:")
        for skip in skips:
            print(f"  [ERROR] {skip.path} :: manifest_parse: {skip.reason}")
    save_registry(entries, root)


def load_registry(root: Path | None = None) -> dict[str, list[RegistryEntry]]:
    root = root or repo_root()
    path = registry_path(root)
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {k: [RegistryEntry(**e) for e in v] for k, v in data.get("entries", {}).items()}


def resolve(
    artifact_id: str,
    version: str | None = None,
    artifact_type: str | None = None,
    root: Path | None = None,
) -> RegistryEntry | None:
    """Resolve an ID to the best matching registry entry."""
    entries = load_registry(root)
    versions = entries.get(artifact_id, [])
    if not versions:
        return None

    if artifact_type:
        versions = [e for e in versions if e.artifact == artifact_type]
        if not versions:
            return None

    if version:
        for e in versions:
            if e.version == version:
                return e
        return None

    try:
        return max(
            versions,
            key=lambda e: tuple(int(x) for x in e.version.split("-")[0].split(".")),
        )
    except ValueError:
        return versions[-1]
