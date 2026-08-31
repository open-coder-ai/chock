"""Tests for manifest advisory rules (warnings only)."""

from __future__ import annotations

from pathlib import Path

import yaml

from chock.manifest import load_manifest
from chock.validation.checks_manifest_advice import check_manifest_advice
from chock.validation.report import Report

MINIMAL_RULE = {
    "id": "test-rule",
    "name": "Test Rule",
    "version": "0.1.0",
    "description": "A test rule.",
    "artifact": "rule",
    "enforcement": "advise",
    "provenance": {
        "author": "a",
        "source_repo": "https://example.com",
        "license": "Apache-2.0",
        "trust_tier": "sandbox",
    },
    "lifecycle": {"status": "draft"},
    "security": {"content_instructions": "never-obey"},
}


def _manifest_dir(tmp_path: Path, policy_id: str, data: dict) -> Path:
    policy_dir = tmp_path / policy_id
    policy_dir.mkdir(parents=True)
    (policy_dir / "manifest.yaml").write_text(yaml.safe_dump(data), encoding="utf-8")
    return policy_dir


def _checks(report: Report) -> set[str]:
    return {f.check for f in report.warnings}


def test_manifest_optimizable_no_evals(tmp_path: Path) -> None:
    """Rule 9: optimization.optimizable true without an evals/ directory."""
    data = {**MINIMAL_RULE, "optimization": {"optimizable": True}}
    policy_dir = _manifest_dir(tmp_path, "test-rule", data)
    report = Report()
    manifest, _ = load_manifest(policy_dir)
    check_manifest_advice(policy_dir, manifest, "rule", report)
    assert "manifest_optimizable_no_evals" in _checks(report)
    assert report.is_clean()


def test_manifest_sandbox_production(tmp_path: Path) -> None:
    """Rule 10: trust_tier sandbox with lifecycle production."""
    data = {
        **MINIMAL_RULE,
        "provenance": {**MINIMAL_RULE["provenance"], "trust_tier": "sandbox"},
        "lifecycle": {"status": "production"},
    }
    policy_dir = _manifest_dir(tmp_path, "test-rule", data)
    report = Report()
    manifest, _ = load_manifest(policy_dir)
    check_manifest_advice(policy_dir, manifest, "rule", report)
    assert "manifest_sandbox_production" in _checks(report)
    assert report.is_clean()


def test_last_validated_cannot_be_an_empty_attestation(tmp_path: Path) -> None:
    """A recorded attestation must carry evidence, or be absent."""
    from chock.validation.loading import load_schema, schema_validator

    validator = schema_validator(load_schema("manifest.schema.json"))

    def errors_for(validation: dict) -> list:
        data = {**MINIMAL_RULE, "enforcement": "block", "rule": {"text": "x"}, "validation": validation}
        return list(validator.iter_errors(data))

    assert errors_for({"last_validated": {}}), "an empty attestation must not validate"
    assert errors_for({"last_validated": {"date": "2026-08-04"}}), "a partial attestation must not validate"
    assert not errors_for({"last_validated": {"date": "2026-08-04", "chock": "0.0.1", "eval_score": 1.0}}), (
        "a complete attestation must validate"
    )


def test_manifest_local_propagation(tmp_path: Path) -> None:
    """Rule 12: enforcement block with propagation local."""
    data = {**MINIMAL_RULE, "enforcement": "block", "propagation": "local"}
    policy_dir = _manifest_dir(tmp_path, "test-rule", data)
    report = Report()
    manifest, _ = load_manifest(policy_dir)
    check_manifest_advice(policy_dir, manifest, "rule", report)
    assert "manifest_local_propagation" in _checks(report)
    assert report.is_clean()


def test_composition_check_sees_unvalidated_skill_type(tmp_path):
    """The composition check runs BEFORE schema validation, so it sees raw values."""
    from pathlib import Path

    from chock.validation.checks_orchestration import check_composition_contract
    from chock.validation.report import Report

    manifest = {
        "id": "x",
        "name": "Orchestrator / X",
        "artifact": "skill",
        "skill": {"skill_type": "workflow"},
        "composition": {"phases": []},
    }
    report = Report()
    check_composition_contract(Path(tmp_path), manifest, "skill", report)

    messages = [f.message for f in report.errors + report.warnings]
    assert not any("composition is only valid for workflow artifacts" in m for m in messages), (
        "the branch was skipped; it is reachable and must stay"
    )
    assert any("monitoring.required" in m for m in messages), f"expected workflow-contract findings, got: {messages}"
