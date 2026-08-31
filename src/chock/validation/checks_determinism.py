"""Chock module (auto-organized from the original monolith)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from chock.manifest import CANONICAL_MANIFEST, resolve_manifest_path
from chock.validation.checks_security import _is_script_file
from chock.validation.patterns import (
    _DETERMINISTIC_HEURISTIC_PATTERNS,
    _INT3_GRANDFATHERED_IDS,
    _VERB_PREFIXES,
)
from chock.validation.report import Finding, Report


def check_verb_first_naming(artifact_dir: Path, manifest: dict[str, Any], artifact_type: str, report: Report) -> None:
    """Check INT-3: warn when a draft/sandbox executing artifact does not start with a verb."""
    if artifact_type == "rule":
        return

    artifact_id = manifest.get("id", "")
    if artifact_id in _INT3_GRANDFATHERED_IDS:
        return

    trust_tier = manifest.get("provenance", {}).get("trust_tier", "sandbox")
    lifecycle_status = manifest.get("lifecycle", {}).get("status", "draft")
    if trust_tier not in {"sandbox"} and lifecycle_status not in {"draft", "review"}:
        return

    first_token = artifact_id.split("-")[0].lower()
    if first_token not in _VERB_PREFIXES:
        report.add(
            Finding(
                str(artifact_dir),
                "interface",
                "warning",
                f"Artifact ID '{artifact_id}' does not start with a verb (INT-3). Suggest rename to a verb-first id, e.g. 'create-...', 'validate-...', 'check-...'",
            )
        )


def check_scripts_shipped(artifact_dir: Path, manifest: dict[str, Any], artifact_type: str, report: Report) -> None:
    """Check DET-1: code/hybrid skills ship deterministic scripts."""
    if artifact_type == "skill":
        skill_type = (manifest.get("skill") or {}).get("skill_type") or manifest.get("skill_type")
        if skill_type not in {"code", "hybrid"}:
            return
        scripts_dir = artifact_dir / "scripts"
        if not scripts_dir.exists() or not scripts_dir.is_dir():
            report.add(
                Finding(
                    str(artifact_dir),
                    "scripts_shipped",
                    "error",
                    f"skill_type '{skill_type}' requires a non-empty scripts/ directory (DET-1).",
                )
            )
            return
        script_files = [p for p in scripts_dir.rglob("*") if _is_script_file(p)]
        if not script_files:
            report.add(
                Finding(
                    str(scripts_dir),
                    "scripts_shipped",
                    "error",
                    "skill_type 'code|hybrid' requires at least one executable script file in scripts/ (DET-1).",
                )
            )
            return
        entrypoint = manifest.get("scripts", {}).get("entrypoint")
        if entrypoint:
            entrypoint_path = scripts_dir / entrypoint
            if not entrypoint_path.exists():
                report.add(
                    Finding(
                        str(resolve_manifest_path(artifact_dir) or (artifact_dir / CANONICAL_MANIFEST)),
                        "scripts_shipped",
                        "error",
                        f"scripts.entrypoint '{entrypoint}' does not resolve in scripts/ (DET-1).",
                    )
                )
        return


def _hash_file(path: Path) -> str:
    """Return sha256 hex digest of a file's contents."""

    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def check_script_integrity(
    artifact_dir: Path, manifest: dict[str, Any], artifact_type: str, root: Path, report: Report
) -> None:
    """Check DET-2: deterministic scripts for production/verified+ artifacts must match registry hashes."""
    if artifact_type not in {"skill", "hook"}:
        return

    provenance = manifest.get("provenance", {})
    trust_tier = provenance.get("trust_tier", "sandbox")
    lifecycle_status = manifest.get("lifecycle", {}).get("status", "draft")
    if trust_tier not in {"verified", "certified"} and lifecycle_status not in {"production", "staging"}:
        return

    registry_file = root / ".chock" / "registry.json"
    if not registry_file.exists():
        report.add(
            Finding(
                str(artifact_dir),
                "script_integrity",
                "error",
                "Production/verified+ artifact requires a registry for script integrity (DET-2).",
            )
        )
        return
    try:
        registry = json.loads(registry_file.read_text(encoding="utf-8"))
        entries = registry.get("entries", {})
    except (json.JSONDecodeError, OSError):
        report.add(
            Finding(
                str(artifact_dir),
                "script_integrity",
                "error",
                "Registry is unreadable; cannot verify script integrity (DET-2).",
            )
        )
        return

    artifact_id = manifest.get("id", "")
    artifact_version = manifest.get("version", "")
    versions = [
        v
        for v in entries.get(artifact_id, [])
        if v.get("artifact") == artifact_type and v.get("version") == artifact_version
    ]
    if not versions:
        report.add(
            Finding(
                str(artifact_dir),
                "script_integrity",
                "error",
                f"No registry entry for {artifact_id} v{artifact_version}; rescan registry (DET-2).",
            )
        )
        return

    expected = versions[0].get("script_hashes", {})
    actual = _compute_script_hashes(artifact_dir, manifest)

    for path, expected_hash in expected.items():
        if path not in actual:
            report.add(
                Finding(
                    str(artifact_dir / path),
                    "script_integrity",
                    "error",
                    f"Script '{path}' missing or not hashed; rescan registry (DET-2).",
                )
            )
        elif actual[path] != expected_hash:
            report.add(
                Finding(
                    str(artifact_dir / path),
                    "script_integrity",
                    "error",
                    f"Hash mismatch for '{path}': registry {expected_hash} vs current {actual[path]} (DET-2).",
                )
            )
    for path in actual:
        if path not in expected:
            report.add(
                Finding(
                    str(artifact_dir / path),
                    "script_integrity",
                    "error",
                    f"Script '{path}' not in registry; rescan registry (DET-2).",
                )
            )


def check_determinization_heuristic(
    artifact_dir: Path, manifest: dict[str, Any], artifact_type: str, report: Report
) -> None:
    """Check DET-3: flag NL skills that contain regex or command-sequence heuristics as determinization candidates."""
    if artifact_type != "skill":
        return
    skill = manifest.get("skill") or {}
    skill_type = skill.get("skill_type") or manifest.get("skill_type")
    if skill_type != "nl":
        return
    if manifest.get("determinization_reviewed"):
        return

    files_to_check = []
    skill_md = artifact_dir / "SKILL.md"
    if skill_md.exists():
        files_to_check.append(skill_md)
    refs_dir = artifact_dir / "references"
    if refs_dir.exists():
        files_to_check.extend(p for p in refs_dir.rglob("*.md") if p.is_file())

    for path in files_to_check:
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for pattern in _DETERMINISTIC_HEURISTIC_PATTERNS:
            if pattern.search(text):
                report.add(
                    Finding(
                        str(path),
                        "determinization",
                        "info",
                        "NL skill contains regex or command-sequence heuristics; consider determinize_edit (DET-3).",
                    )
                )
                return


def _compute_script_hashes(artifact_dir: Path, manifest: dict[str, Any]) -> dict[str, str]:
    """Compute sha256 hashes for deterministic scripts shipped with an artifact."""
    artifact_type = manifest.get("artifact", "")
    hashes: dict[str, str] = {}

    if artifact_type == "skill":
        scripts_dir = artifact_dir / "scripts"
        if scripts_dir.exists():
            for path in scripts_dir.rglob("*"):
                if path.is_file():
                    rel = path.relative_to(scripts_dir).as_posix()
                    hashes[rel] = _hash_file(path)
        return hashes

    if artifact_type == "hook":
        impl_dir = artifact_dir / "implementations"
        if impl_dir.exists():
            for path in impl_dir.rglob("*"):
                if path.is_file():
                    rel = path.relative_to(impl_dir).as_posix()
                    hashes[rel] = _hash_file(path)
        return hashes

    return hashes
