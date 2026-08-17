"""Chock module (auto-organized from the original monolith)."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any

import yaml

from chock.manifest import MANIFEST_NAMES, ManifestSourceError, load_manifest
from chock.validation.checks_content import (
    check_description_parity,
    check_no_agent_specific_leakage,
    check_progressive_disclosure,
    check_token_budgets,
    check_yagni,
)
from chock.validation.checks_determinism import (
    check_determinization_heuristic,
    check_script_integrity,
    check_scripts_shipped,
    check_verb_first_naming,
)
from chock.validation.checks_drift import (
    check_compiled_drift,
    check_plugin_drift,
    check_registry_freshness,
)
from chock.validation.checks_evals import check_eval_first
from chock.validation.checks_manifest_advice import check_manifest_advice
from chock.validation.checks_manifest_schema import check_manifest_schema
from chock.validation.checks_orchestration import (
    check_composition_contract,
    check_dependencies_resolvable,
    check_lifecycle_guards,
    check_subagent_contract,
    check_trust_tier,
)
from chock.validation.checks_policy_toggles import check_policy_toggles
from chock.validation.checks_repo import (
    check_adapter_integrity,
    check_ambient_rule_blocks,
    check_ambient_token_budget,
    check_release_consistency,
)
from chock.validation.checks_security import (
    check_ambient_tier,
    check_effects_and_approval,
    check_security_baseline,
)
from chock.validation.frontier import check_frontier_mode
from chock.validation.loading import (
    discover_artifacts,
    load_schema,
    validate_yaml_against_schema,
)
from chock.validation.report import Finding, Report, emit


def validate_artifact(
    artifact_type: str,
    artifact_dir: Path,
    mode: str,
    report: Report,
    root: Path,
    *,
    registry_check: bool = True,
) -> None:
    manifest: dict[str, Any] = {}
    manifest_path: Path | None = None
    warnings: list[str] = []

    try:
        result = load_manifest(artifact_dir, warnings=warnings)
    except (yaml.YAMLError, OSError, ManifestSourceError) as exc:
        report.add(Finding(str(artifact_dir), "manifest_parse", "error", f"{type(exc).__name__}: {exc}"))
        return
    if result is not None:
        manifest, manifest_path = result

    for warning in warnings:
        report.add(Finding(str(manifest_path or artifact_dir), "manifest_default", "warning", warning))

    schema_name = {
        "rule": "manifest.schema.json",
        "hook": "manifest.schema.json",
        "skill": "manifest.schema.json",
        "workflow": "manifest.schema.json",
        "eval": "eval.schema.json",
        "subagent": "subagent.schema.json",
    }.get(artifact_type)

    if schema_name and manifest:
        schema = load_schema(schema_name)
        validate_yaml_against_schema(manifest, schema, str(manifest_path or artifact_dir), report)
    elif manifest and manifest_path and manifest_path.name in MANIFEST_NAMES:
        base_schema = load_schema("manifest.schema.json")
        validate_yaml_against_schema(manifest, base_schema, str(manifest_path), report)

    # Deterministic framework checks
    check_token_budgets(artifact_dir, manifest, artifact_type, report)
    check_progressive_disclosure(artifact_dir, manifest, artifact_type, report)
    check_yagni(artifact_dir, manifest, artifact_type, report)
    check_eval_first(artifact_dir, manifest, artifact_type, report)
    check_no_agent_specific_leakage(artifact_dir, manifest, artifact_type, report)
    check_security_baseline(artifact_dir, manifest, artifact_type, report)
    check_effects_and_approval(artifact_dir, manifest, artifact_type, report)
    check_scripts_shipped(artifact_dir, manifest, artifact_type, report)
    check_script_integrity(artifact_dir, manifest, artifact_type, root, report)
    check_determinization_heuristic(artifact_dir, manifest, artifact_type, report)
    check_description_parity(artifact_dir, manifest, artifact_type, report)
    check_composition_contract(artifact_dir, manifest, artifact_type, report)
    check_subagent_contract(artifact_dir, manifest, artifact_type, report)
    check_dependencies_resolvable(artifact_dir, manifest, artifact_type, root, report)
    check_lifecycle_guards(artifact_dir, manifest, artifact_type, report)
    check_trust_tier(artifact_dir, manifest, artifact_type, report)
    check_ambient_tier(artifact_dir, manifest, artifact_type, report)
    check_verb_first_naming(artifact_dir, manifest, artifact_type, report)
    check_manifest_schema(artifact_dir, manifest, artifact_type, report)
    check_manifest_advice(artifact_dir, manifest, artifact_type, report)

    if registry_check:
        check_registry_freshness(artifact_dir, manifest, artifact_type, root, report)

    if mode.startswith("frontier-"):
        check_frontier_mode(artifact_dir, manifest, artifact_type, mode, report)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Chock deterministic artifact validator")
    parser.add_argument("path", nargs="?", default=".", help="Root path to validate")
    parser.add_argument(
        "--mode",
        default="agnostic",
        choices=[
            "agnostic",
            "frontier-agentskills",
            "frontier-claude",
            "frontier-openai",
            "frontier-devin",
            "frontier-cursor",
            "frontier-copilot",
            "frontier-codex",
        ],
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON report")
    parser.add_argument("--include", action="append", default=[], help="Limit to artifact type (repeatable)")
    parser.add_argument(
        "--exclude",
        action="append",
        default=[],
        help="Skip artifact directories whose path contains this substring (repeatable)",
    )
    parser.add_argument("--no-registry-check", action="store_true", help="Disable registry freshness check")
    parser.add_argument(
        "--event",
        choices=["commit"],
        help="Context this run happens in. 'commit' scopes drift severity to the staged diff.",
    )
    args = parser.parse_args(argv)

    root = Path(args.path).resolve()
    if not root.exists():
        print(f"Path does not exist: {root}", file=sys.stderr)
        return 2

    report = Report()

    normalized_excludes = [e.replace("/", os.sep).replace("\\", os.sep) for e in args.exclude]
    for artifact_type, artifact_dir in discover_artifacts(root):
        if args.include and artifact_type not in args.include:
            continue
        norm_path = str(artifact_dir).replace("/", os.sep).replace("\\", os.sep)
        if any(exclude in norm_path for exclude in normalized_excludes):
            continue
        validate_artifact(
            artifact_type,
            artifact_dir,
            args.mode,
            report,
            root,
            registry_check=not args.no_registry_check,
        )

    check_ambient_rule_blocks(root, report)
    check_adapter_integrity(root, report)
    check_release_consistency(root, report)
    check_ambient_token_budget(root, report)
    check_policy_toggles(root, report)
    check_compiled_drift(root, report, event=args.event)
    check_plugin_drift(root, report, event=args.event)

    emit(report, args.json)
    return 0 if report.is_clean() else 1
