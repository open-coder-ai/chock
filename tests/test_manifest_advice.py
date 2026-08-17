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
    """A recorded attestation must carry evidence, or be absent.

    The old `manifest_unvalidated_block` check warned whenever a block policy had no
    `validation.last_validated`. Nothing could satisfy it honestly: there is no eval
    runner, so neither we nor an adopter can validate a policy, and the schema required no
    fields -- meaning the only way to clear the warning was to write `{}` or invent a date.
    A check whose only satisfying action is fabrication manufactures the false verification
    this project exists to prevent, so it was removed.

    What replaces it is this: the field stays optional, but writing it partially is now a
    schema error. Looking validated and being validated are the same thing again.
    """
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
    """The composition check runs BEFORE schema validation, so it sees raw values.

    A design review originally argued the
    `skill_type == "workflow"` branch in checks_orchestration.py was dead code, because the
    schema constrains skillType to nl|code|hybrid. The schema does — but engine.py calls
    check_composition_contract before check_manifest_schema, so an out-of-enum value has not
    been rejected yet and the branch is reachable.

    This pins the behaviour so the branch is not deleted as a cleanup: doing so would
    suppress the workflow-contract findings below in favour of a later, less specific
    schema error.
    """
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
