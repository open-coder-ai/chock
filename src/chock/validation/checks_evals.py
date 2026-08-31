"""Eval-suite conformance checks: existence, minimum categories, adversarial coverage."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from chock.validation.loading import (
    ARTIFACT_TYPES,
    BUDGETS,
    load_schema,
    validate_yaml_against_schema,
)
from chock.validation.report import Finding, Report


def _schema_validate_suite(suite_file: Path, report: Report) -> None:
    """Validate an eval suite file against the canonical eval schema."""
    try:
        doc = yaml.safe_load(suite_file.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        report.add(Finding(str(suite_file), "eval_first", "error", f"Invalid YAML: {exc}"))
        return

    schema = load_schema("eval.schema.json")
    validate_yaml_against_schema(doc, schema, str(suite_file), report)


def check_eval_first(artifact_dir: Path, manifest: dict[str, Any], artifact_type: str, report: Report) -> None:
    """Eval suite must exist and meet minimum case counts before an artifact is valid."""
    if artifact_type not in ARTIFACT_TYPES:
        return

    eval_dir = artifact_dir / "evals"
    suite_file = eval_dir / "suite.yaml"
    if not suite_file.exists():
        report.add(
            Finding(
                str(artifact_dir),
                "eval_first",
                "error",
                "Missing evals/suite.yaml. Create eval cases before finalizing the artifact.",
            )
        )
        return

    _schema_validate_suite(suite_file, report)

    try:
        doc = yaml.safe_load(suite_file.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        report.add(Finding(str(suite_file), "eval_first", "error", f"Invalid YAML: {exc}"))
        return

    if not isinstance(doc, dict):
        report.add(Finding(str(suite_file), "eval_first", "error", "Eval suite must be a YAML mapping."))
        return
    suite = doc.get("eval_suite", doc.get("suite", {}))
    if not isinstance(suite, dict):
        report.add(Finding(str(suite_file), "eval_first", "error", "eval_suite must be a mapping."))
        return
    cases = suite.get("cases", suite.get("test_cases", []))
    if not isinstance(cases, list):
        report.add(Finding(str(suite_file), "eval_first", "error", "cases must be a list."))
        return
    cases = [c for c in cases if isinstance(c, dict)]
    categories = [str(c.get("category", c.get("type", ""))).lower() for c in cases]
    if len(cases) < BUDGETS["eval_suite_min_cases"]:
        report.add(
            Finding(
                str(suite_file),
                "eval_first",
                "error",
                f"Eval suite has {len(cases)} case(s); need >= {BUDGETS['eval_suite_min_cases']}.",
            )
        )
    if categories.count("trigger") < BUDGETS["eval_trigger_cases_min"]:
        report.add(
            Finding(
                str(suite_file), "eval_first", "error", f"Need >= {BUDGETS['eval_trigger_cases_min']} trigger case(s)."
            )
        )
    if categories.count("negative_trigger") < BUDGETS["eval_negative_trigger_cases_min"]:
        report.add(
            Finding(
                str(suite_file),
                "eval_first",
                "error",
                f"Need >= {BUDGETS['eval_negative_trigger_cases_min']} negative_trigger case(s).",
            )
        )
    if categories.count("behavior") < BUDGETS["eval_behavior_cases_min"]:
        report.add(
            Finding(
                str(suite_file),
                "eval_first",
                "error",
                f"Need >= {BUDGETS['eval_behavior_cases_min']} behavior case(s).",
            )
        )

    if artifact_type == "skill" and manifest.get("security", {}).get("processes_external_content"):
        if categories.count("adversarial") < 1 and categories.count("security") < 1:
            report.add(
                Finding(
                    str(suite_file),
                    "eval_first",
                    "error",
                    "security.processes_external_content is true but eval suite has no adversarial or security case (SEC-6).",
                )
            )
