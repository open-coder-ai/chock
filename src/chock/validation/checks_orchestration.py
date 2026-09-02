"""Chock module (auto-organized from the original monolith)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from chock.manifest import CANONICAL_MANIFEST, CONTENT_INSTRUCTIONS_KEY, resolve_manifest_path
from chock.validation.report import Finding, Report


def _manifest_ref(artifact_dir: Path) -> str:
    return str(resolve_manifest_path(artifact_dir) or (artifact_dir / CANONICAL_MANIFEST))


_COMPOSITION_MODES = {"sequential", "fan_out", "fan_in", "human_checkpoint"}
_TERMINAL_HANDOFF_FIELDS = {"work_item_id", "phase", "status", "outcome", "error"}


def check_dependencies_resolvable(
    artifact_dir: Path, manifest: dict[str, Any], artifact_type: str, root: Path, report: Report
) -> None:
    """Ensure declared skill and subagent dependencies exist in the registry."""
    registry_file = root / ".chock" / "registry.json"
    if not registry_file.exists():
        return

    try:
        registry = json.loads(registry_file.read_text(encoding="utf-8"))
        known_ids = set(registry.get("entries", {}).keys())
    except (json.JSONDecodeError, OSError):
        return

    deps: list[tuple[str | None, str]] = []
    if artifact_type == "subagent":
        delegated_skill = manifest.get("delegates", {}).get("skill")
        if delegated_skill:
            deps.append((delegated_skill, "skill"))
    deps_data = manifest.get("dependencies", {})
    for dep in deps_data.get("skills", []):
        if dep.get("optional"):
            continue
        deps.append((dep.get("id"), "skill"))
    for dep in deps_data.get("subagents", []):
        if dep.get("optional"):
            continue
        deps.append((dep.get("id"), "subagent"))

    for dep_id, expected_type in deps:
        if not dep_id:
            continue
        if dep_id not in known_ids:
            report.add(Finding(str(artifact_dir), "dependencies", "error", f"Dependency '{dep_id}' is not registered."))
            continue
        entries = registry.get("entries", {}).get(dep_id, [])
        if expected_type not in {entry.get("artifact") for entry in entries}:
            report.add(
                Finding(
                    str(artifact_dir),
                    "dependencies",
                    "error",
                    f"Dependency '{dep_id}' is not registered as artifact '{expected_type}'.",
                )
            )


def check_subagent_contract(artifact_dir: Path, manifest: dict[str, Any], artifact_type: str, report: Report) -> None:
    """Check delegated skill and isolation requirements for workflow subagents."""
    if artifact_type != "subagent" or not (manifest.get("delegates") or manifest.get("execution_scope")):
        return
    manifest_ref = str(artifact_dir / "subagent.yaml")
    if not manifest.get("delegates", {}).get("skill"):
        report.add(Finding(manifest_ref, "handoff", "error", "Workflow subagents must declare delegates.skill."))
    scope = manifest.get("execution_scope", {})
    isolation = scope.get("isolation", {})
    if not scope.get("input_key"):
        report.add(
            Finding(manifest_ref, "handoff", "error", "Workflow subagents must declare execution_scope.input_key.")
        )
    if isolation.get("required") is not True:
        report.add(
            Finding(
                manifest_ref,
                "isolation",
                "error",
                "Workflow subagents require execution_scope.isolation.required: true.",
            )
        )
    if not isolation.get("boundary"):
        report.add(Finding(manifest_ref, "isolation", "error", "Workflow subagents require an isolation boundary."))
    output_schema = manifest.get("output_schema", {})
    output_properties = output_schema.get("properties", {})
    required = set(output_schema.get("required", []))
    for field in ("work_item_id", "phase", "status", "outcome"):
        if field not in output_properties or field not in required:
            report.add(Finding(manifest_ref, "handoff", "error", f"Subagent output_schema must require '{field}'."))


def check_composition_contract(
    artifact_dir: Path, manifest: dict[str, Any], artifact_type: str, report: Report
) -> None:
    """Check agent-driven workflow phases, handoff, and monitoring contracts."""
    is_workflow = artifact_type == "workflow"
    skill = manifest.get("skill") or {}
    skill_type = skill.get("skill_type") or manifest.get("skill_type")
    if not is_workflow and not (artifact_type == "skill" and skill_type == "workflow"):
        if manifest.get("composition") is not None:
            manifest_ref = _manifest_ref(artifact_dir)
            report.add(
                Finding(manifest_ref, "composition", "error", "composition is only valid for workflow artifacts.")
            )
        return

    composition = manifest.get("composition")
    manifest_ref = _manifest_ref(artifact_dir)

    if is_workflow and not str(manifest.get("name", "")).startswith("Orchestrator /"):
        report.add(
            Finding(
                manifest_ref,
                "composition",
                "warning",
                "Workflow artifacts should use the default name prefix 'Orchestrator /'.",
            )
        )

    if not isinstance(composition, dict):
        report.add(Finding(manifest_ref, "composition", "error", "Composite artifacts must declare composition."))
        return

    phases = composition.get("phases", [])
    monitoring = composition.get("monitoring", {})
    handoff = composition.get("handoff", {})
    if not monitoring.get("required"):
        report.add(
            Finding(
                manifest_ref, "monitoring", "error", "Composite skills require composition.monitoring.required: true."
            )
        )
    if not handoff.get("required"):
        report.add(
            Finding(manifest_ref, "handoff", "error", "Composite skills require composition.handoff.required: true.")
        )
    if not _TERMINAL_HANDOFF_FIELDS.issubset(set(handoff.get("required_fields", []))):
        report.add(
            Finding(
                manifest_ref,
                "handoff",
                "error",
                "Handoff required_fields must include work_item_id, phase, status, outcome, and error.",
            )
        )

    phase_ids: set[str] = set()
    declared_skills = {dep.get("id") for dep in manifest.get("dependencies", {}).get("skills", [])}
    declared_subagents = {dep.get("id") for dep in manifest.get("dependencies", {}).get("subagents", [])}
    for phase in phases:
        phase_id = phase.get("id")
        if phase_id in phase_ids:
            report.add(Finding(manifest_ref, "composition", "error", f"Duplicate composition phase '{phase_id}'."))
        phase_ids.add(phase_id)
        mode = phase.get("mode")
        if mode not in _COMPOSITION_MODES:
            report.add(Finding(manifest_ref, "composition", "error", f"Unsupported composition mode '{mode}'."))
        if not phase.get("monitoring", {}).get("required"):
            report.add(Finding(manifest_ref, "monitoring", "error", f"Phase '{phase_id}' requires monitoring."))
        if mode in {"fan_out", "fan_in"}:
            if not phase.get("source"):
                report.add(Finding(manifest_ref, "composition", "error", f"Phase '{phase_id}' requires source."))
            result = phase.get("result", {})
            if not result.get("correlation_key"):
                report.add(
                    Finding(manifest_ref, "handoff", "error", f"Phase '{phase_id}' requires a result correlation_key.")
                )
        if mode == "fan_out":
            isolation = phase.get("isolation", {})
            if isolation.get("required") is not True:
                report.add(
                    Finding(manifest_ref, "isolation", "error", f"Fan-out phase '{phase_id}' requires isolation.")
                )
            if not phase.get("concurrency", {}).get("max_parallel"):
                report.add(
                    Finding(
                        manifest_ref, "monitoring", "error", f"Fan-out phase '{phase_id}' requires bounded concurrency."
                    )
                )
        if mode == "human_checkpoint" and phase.get("approval", {}).get("required") is not True:
            report.add(Finding(manifest_ref, "approval", "error", f"Checkpoint phase '{phase_id}' requires approval."))
        invoke = phase.get("invoke", {})
        if invoke.get("skill") and invoke["skill"] not in declared_skills:
            report.add(
                Finding(
                    manifest_ref,
                    "dependencies",
                    "error",
                    f"Phase '{phase_id}' invokes undeclared skill '{invoke['skill']}'.",
                )
            )
        if invoke.get("subagent") and invoke["subagent"] not in declared_subagents:
            report.add(
                Finding(
                    manifest_ref,
                    "dependencies",
                    "error",
                    f"Phase '{phase_id}' invokes undeclared subagent '{invoke['subagent']}'.",
                )
            )


def check_lifecycle_guards(artifact_dir: Path, manifest: dict[str, Any], artifact_type: str, report: Report) -> None:
    """Check spec §8 lifecycle transition guards."""
    lifecycle = manifest.get("lifecycle", {})
    status = lifecycle.get("status", "draft")
    changelog = manifest.get("changelog", [])

    if status == "review":
        security = manifest.get("security", {})
        if security.get(CONTENT_INSTRUCTIONS_KEY) != "never-obey":
            report.add(
                Finding(
                    _manifest_ref(artifact_dir),
                    "lifecycle",
                    "error",
                    "Lifecycle transition to review requires security.content_instructions: never-obey.",
                )
            )

    if status == "production" and not lifecycle.get("reviewed_by"):
        report.add(
            Finding(
                _manifest_ref(artifact_dir),
                "lifecycle",
                "warning",
                "Production artifact should record reviewed_by.",
            )
        )

    if status == "deprecated":
        if not lifecycle.get("replacement_id"):
            report.add(
                Finding(
                    _manifest_ref(artifact_dir),
                    "lifecycle",
                    "error",
                    "Deprecated artifact must set lifecycle.replacement_id.",
                )
            )
        if not any("deprecat" in str(entry.get("changes", [])).lower() for entry in changelog):
            report.add(
                Finding(
                    _manifest_ref(artifact_dir),
                    "lifecycle",
                    "error",
                    "Deprecated artifact must note deprecation in changelog.",
                )
            )


def check_trust_tier(artifact_dir: Path, manifest: dict[str, Any], artifact_type: str, report: Report) -> None:
    """Check spec §9 trust tier rules."""
    provenance = manifest.get("provenance", {})
    lifecycle = manifest.get("lifecycle", {})
    trust_tier = provenance.get("trust_tier", "sandbox")
    status = lifecycle.get("status", "draft")

    if trust_tier in {"verified", "certified"} and status not in {"review", "staging", "production", "deprecated"}:
        report.add(
            Finding(
                _manifest_ref(artifact_dir),
                "trust_tier",
                "warning",
                f"Trust tier '{trust_tier}' requires lifecycle status at least 'review'.",
            )
        )
