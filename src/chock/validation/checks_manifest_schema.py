"""Structural manifest rules that always produce errors."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from chock.manifest import CANONICAL_MANIFEST, resolve_manifest_path
from chock.policy_id import InvalidPolicyId, validate_policy_id
from chock.validation.checks_gate_shape import _validate_gate
from chock.validation.report import Finding, Report

_PAYLOADS: dict[str, set[str]] = {
    "rule": {"rule"},
    "hook": {"hook"},
    "skill": {"skill"},
    "workflow": {"workflow"},
}

_ALL_PAYLOAD_KEYS: set[str] = set().union(*_PAYLOADS.values())


def _manifest_ref(artifact_dir: Path) -> Path:
    return resolve_manifest_path(artifact_dir) or (artifact_dir / CANONICAL_MANIFEST)


def _check_manifest_id_folder(artifact_dir: Path, manifest: dict[str, Any], report: Report) -> None:
    # Validate the *effective* id -- the folder name when no id field is present -- against
    # the same rule compile and add enforce. Checking only a present id field left the
    # defaulted-id path (an unsafe folder name, no id) unvalidated, while compile still turns
    # that name into a shell token and an output path.
    effective_id = manifest.get("id") or artifact_dir.name
    try:
        validate_policy_id(effective_id, artifact_dir.name)
    except InvalidPolicyId as exc:
        report.add(Finding(str(_manifest_ref(artifact_dir)), "manifest_id_folder", "error", str(exc)))


def _check_manifest_payload(artifact_dir: Path, manifest: dict[str, Any], report: Report) -> None:
    artifact = manifest.get("artifact")
    allowed = _PAYLOADS.get(artifact)
    if allowed is None:
        return

    present = {k for k in manifest if k in _ALL_PAYLOAD_KEYS}
    disallowed = present - allowed
    if disallowed:
        report.add(
            Finding(
                str(_manifest_ref(artifact_dir)),
                "manifest_payload",
                "error",
                f"artifact '{artifact}' has disallowed payload keys: {sorted(disallowed)}",
            )
        )
        return

    own = present & allowed
    if len(own) != 1:
        report.add(
            Finding(
                str(_manifest_ref(artifact_dir)),
                "manifest_payload",
                "error",
                f"artifact '{artifact}' requires exactly one of {sorted(allowed)}",
            )
        )


def _check_manifest_block_needs_gate(artifact_dir: Path, manifest: dict[str, Any], report: Report) -> None:
    enforcement = manifest.get("enforcement")
    if enforcement not in {"block", "verify"}:
        return

    hook_gate = (manifest.get("hook") or {}).get("gate")

    if hook_gate:
        _validate_gate(hook_gate, str(_manifest_ref(artifact_dir)), report, tool_use_allowed=True)
        return

    report.add(
        Finding(
            str(_manifest_ref(artifact_dir)),
            "manifest_block_needs_gate",
            "error",
            f"enforcement is '{enforcement}' but no hook.gate definition found",
        )
    )


def _check_manifest_self_dependency(artifact_dir: Path, manifest: dict[str, Any], report: Report) -> None:
    own_id = manifest.get("id") or artifact_dir.name
    for dep in (manifest.get("dependencies") or {}).get("policies") or []:
        if dep.get("id") == own_id:
            report.add(
                Finding(
                    str(_manifest_ref(artifact_dir)),
                    "manifest_self_dependency",
                    "error",
                    f"policy declares itself as a dependency: {own_id}",
                )
            )


def _check_manifest_self_conflict(artifact_dir: Path, manifest: dict[str, Any], report: Report) -> None:
    own_id = manifest.get("id") or artifact_dir.name
    for conflict in manifest.get("conflicts_with") or []:
        if conflict.get("id") == own_id:
            report.add(
                Finding(
                    str(_manifest_ref(artifact_dir)),
                    "manifest_self_conflict",
                    "error",
                    f"policy declares itself in conflicts_with: {own_id}",
                )
            )


def _check_manifest_bundle_assets(artifact_dir: Path, manifest: dict[str, Any], report: Report) -> None:
    shared_assets = (manifest.get("bundle") or {}).get("shared_assets") or []
    if not shared_assets:
        return

    base = artifact_dir.resolve()
    manifest_ref = _manifest_ref(artifact_dir)
    for asset in shared_assets:
        if not isinstance(asset, str):
            continue

        resolved = (base / asset).resolve()
        try:
            resolved.relative_to(base)
        except ValueError:
            report.add(
                Finding(
                    str(manifest_ref),
                    "manifest_bundle_assets",
                    "error",
                    f"shared asset escapes policy directory: {asset!r}",
                )
            )
            continue

        if not resolved.exists():
            report.add(
                Finding(
                    str(manifest_ref),
                    "manifest_bundle_assets",
                    "error",
                    f"shared asset does not exist: {asset!r}",
                )
            )


def _check_manifest_workflow_uses(artifact_dir: Path, manifest: dict[str, Any], report: Report) -> None:
    if manifest.get("artifact") != "workflow":
        return

    dep_ids = {d.get("id") for d in (manifest.get("dependencies") or {}).get("policies") or []}
    steps = (manifest.get("workflow") or {}).get("steps") or []
    for step in steps:
        uses = step.get("uses")
        if uses not in dep_ids:
            report.add(
                Finding(
                    str(_manifest_ref(artifact_dir)),
                    "manifest_workflow_uses",
                    "error",
                    f"workflow step uses '{uses}' which is not declared in dependencies.policies",
                )
            )


def check_manifest_schema(artifact_dir, manifest: dict[str, Any], artifact_type: str, report: Report) -> None:
    """Validate structural manifest invariants that are errors."""
    artifact_dir = Path(artifact_dir)
    _check_manifest_id_folder(artifact_dir, manifest, report)
    _check_manifest_payload(artifact_dir, manifest, report)
    _check_manifest_block_needs_gate(artifact_dir, manifest, report)
    _check_manifest_self_dependency(artifact_dir, manifest, report)
    _check_manifest_self_conflict(artifact_dir, manifest, report)
    _check_manifest_bundle_assets(artifact_dir, manifest, report)
    _check_manifest_workflow_uses(artifact_dir, manifest, report)
