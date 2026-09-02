"""Manifest-level advisory rules that never make a report dirty."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from chock.manifest import CANONICAL_MANIFEST, resolve_manifest_path
from chock.validation.report import Finding, Report


def _manifest_ref(artifact_dir: Path) -> Path:
    return resolve_manifest_path(artifact_dir) or (artifact_dir / CANONICAL_MANIFEST)


def _check_manifest_optimizable_no_evals(artifact_dir: Path, manifest: dict[str, Any], report: Report) -> None:
    optimization = manifest.get("optimization") or {}
    if optimization.get("optimizable") and not (artifact_dir / "evals").is_dir():
        report.add(
            Finding(
                str(_manifest_ref(artifact_dir)),
                "manifest_optimizable_no_evals",
                "warning",
                "optimization.optimizable is true but no evals/ directory exists",
            )
        )


def _check_manifest_sandbox_production(artifact_dir: Path, manifest: dict[str, Any], report: Report) -> None:
    trust_tier = (manifest.get("provenance") or {}).get("trust_tier")
    status = (manifest.get("lifecycle") or {}).get("status")
    if trust_tier == "sandbox" and status == "production":
        report.add(
            Finding(
                str(_manifest_ref(artifact_dir)),
                "manifest_sandbox_production",
                "warning",
                "trust_tier 'sandbox' is not appropriate for production status",
            )
        )


def _check_manifest_local_propagation(artifact_dir: Path, manifest: dict[str, Any], report: Report) -> None:
    if manifest.get("enforcement") == "block" and manifest.get("propagation") == "local":
        report.add(
            Finding(
                str(_manifest_ref(artifact_dir)),
                "manifest_local_propagation",
                "warning",
                "enforcement is 'block' with propagation 'local' — this is a deliberate weakening of inheritance",
            )
        )


def check_manifest_advice(artifact_dir, manifest: dict[str, Any], _artifact_type: str, report: Report) -> None:
    """Validate structural manifest invariants that are warnings only."""
    artifact_dir = Path(artifact_dir)
    _check_manifest_optimizable_no_evals(artifact_dir, manifest, report)
    _check_manifest_sandbox_production(artifact_dir, manifest, report)
    _check_manifest_local_propagation(artifact_dir, manifest, report)
