"""Validation tests for the unified manifest.schema.json."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest
import yaml
from conftest import baseline_policy

from chock.validation.loading import ARTIFACT_TYPES, get_validator

VALIDATOR = get_validator("manifest.schema.json")


def _base() -> dict:
    return {
        "id": "demo-policy",
        "name": "Demo",
        "version": "0.1.0",
        "description": "D" * 1024,
        "artifact": "rule",
        "enforcement": "advise",
        "provenance": {
            "author": "a",
            "source_repo": "https://example.com",
            "license": "Apache-2.0",
            "trust_tier": "sandbox",
        },
        "lifecycle": {"status": "draft"},
    }


def _rule() -> dict:
    return {**_base(), "rule": {"text": "never(foo): bar"}}


def _hook() -> dict:
    return {
        **_base(),
        "artifact": "hook",
        "enforcement": "block",
        "hook": {
            "gate": {
                "kind": "content_regex",
                "on": ["commit"],
                "action": "block",
                "message": "blocked",
                "params": {"scan": "added_lines", "content_pattern": "TODO"},
            }
        },
    }


def _skill_payload() -> dict:
    return {
        **_base(),
        "artifact": "skill",
        "enforcement": "advise",
        "effects": ["none"],
        "evaluation": {"test_suite_ref": "evals/suite.yaml"},
        "input_schema": {
            "type": "object",
            "properties": {"request": {"type": "string", "description": "request"}},
            "required": ["request"],
            "additionalProperties": False,
        },
        "output_schema": {
            "type": "object",
            "properties": {
                "outcome": {
                    "type": "string",
                    "enum": ["success", "failure", "needs_handoff"],
                    "description": "outcome",
                }
            },
            "required": ["outcome"],
            "additionalProperties": False,
        },
        "security": {"content_instructions": "never-obey"},
        "skill": {"skill_type": "hybrid", "entry": "SKILL.md", "effects": ["none"], "approval": {"required": False}},
    }


def _workflow() -> dict:
    return {
        **_base(),
        "artifact": "workflow",
        "workflow": {
            "effects": ["read_only"],
            "approval": {"required": False},
            "control": "deterministic",
            "steps": [{"id": "scan", "uses": "scan-secrets"}],
        },
    }


@pytest.mark.parametrize(
    "manifest",
    [_rule(), _hook(), _skill_payload(), _workflow()],
    ids=["rule", "hook", "skill-payload", "workflow"],
)
def test_artifact_type_validates(manifest: dict) -> None:
    VALIDATOR.validate(instance=manifest)


def test_wrong_payload_for_artifact_errors() -> None:
    manifest = _rule()
    manifest["skill"] = manifest.pop("rule")
    manifest["artifact"] = "rule"
    with pytest.raises(jsonschema.ValidationError):
        VALIDATOR.validate(instance=manifest)


def test_two_payloads_error() -> None:
    manifest = _rule()
    manifest["hook"] = {
        "gate": {
            "kind": "forbidden_ref",
            "on": ["push"],
            "action": "block",
            "message": "blocked",
            "params": {"refs": ["main"]},
        }
    }
    with pytest.raises(jsonschema.ValidationError):
        VALIDATOR.validate(instance=manifest)


def test_unknown_top_level_key_errors() -> None:
    manifest = _rule()
    manifest["unknown_field"] = True
    with pytest.raises(jsonschema.ValidationError):
        VALIDATOR.validate(instance=manifest)


def test_provenance_typo_rejected() -> None:
    manifest = _rule()
    manifest["provenance"]["licence"] = manifest["provenance"].pop("license")
    with pytest.raises(jsonschema.ValidationError):
        VALIDATOR.validate(instance=manifest)


def test_tool_use_event_validates() -> None:
    manifest = _hook()
    manifest["hook"]["gate"]["on"] = ["tool_use"]
    VALIDATOR.validate(instance=manifest)


def test_description_budget() -> None:
    manifest = _rule()
    manifest["description"] = "D" * 1024
    VALIDATOR.validate(instance=manifest)

    manifest["description"] = "D" * 1025
    with pytest.raises(jsonschema.ValidationError):
        VALIDATOR.validate(instance=manifest)


def test_gate_on_empty_rejected() -> None:
    """B3 guard: hook.gate.on == [] is a silent no-op and must be rejected by the schema."""
    manifest = _hook()
    manifest["hook"]["gate"]["on"] = []
    with pytest.raises(jsonschema.ValidationError):
        VALIDATOR.validate(instance=manifest)


def test_gate_message_empty_rejected() -> None:
    """B3 guard: a blocking gate with an empty message gives the developer no actionable
    alternative and must be rejected by the schema."""
    manifest = _hook()
    manifest["hook"]["gate"]["message"] = ""
    with pytest.raises(jsonschema.ValidationError):
        VALIDATOR.validate(instance=manifest)


def test_baseline_gates_validate() -> None:
    """The two real baseline gates (scan-secrets, protect-main-branch) must validate
    against the v3 manifest schema. Replaces test_scan_secrets_gate_is_valid and
    test_protect_main_branch_gate_is_valid from the deleted test_gate_validation.py."""
    for policy_id in ("scan-secrets", "protect-main-branch"):
        manifest_path = baseline_policy(policy_id) / "manifest.yaml"
        with manifest_path.open(encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        VALIDATOR.validate(instance=data)


def test_propagation_default(tmp_path: Path) -> None:
    """propagation resolves to 'inherit' when absent and enforcement is not 'advise'."""
    from chock.manifest import load_manifest

    rule_dir = tmp_path / "test-rule"
    rule_dir.mkdir()
    rule_dir.joinpath("manifest.yaml").write_text(
        yaml.safe_dump(
            {
                "id": "test-rule",
                "name": "Test",
                "version": "0.1.0",
                "description": "d",
                "artifact": "rule",
                "enforcement": "block",
                "provenance": {
                    "author": "a",
                    "source_repo": "https://example.com",
                    "license": "Apache-2.0",
                    "trust_tier": "sandbox",
                },
                "lifecycle": {"status": "draft"},
                "rule": {"text": "never(x): y"},
            }
        ),
        encoding="utf-8",
    )

    data, _ = load_manifest(rule_dir)
    assert data["propagation"] == "inherit"

    # 'advise' does not receive a default.
    advise_dir = tmp_path / "test-advise"
    advise_dir.mkdir()
    advise_dir.joinpath("manifest.yaml").write_text(
        yaml.safe_dump(
            {
                "id": "test-advise",
                "name": "Test",
                "version": "0.1.0",
                "description": "d",
                "artifact": "rule",
                "enforcement": "advise",
                "provenance": {
                    "author": "a",
                    "source_repo": "https://example.com",
                    "license": "Apache-2.0",
                    "trust_tier": "sandbox",
                },
                "lifecycle": {"status": "draft"},
                "rule": {"text": "never(x): y"},
            }
        ),
        encoding="utf-8",
    )

    data_advise, _ = load_manifest(advise_dir)
    assert "propagation" not in data_advise


EXPECTED_ARTIFACTS = {"rule", "hook", "skill", "workflow"}
SCHEMA_PATH = (
    Path(__file__).resolve().parent.parent / "src" / "chock" / "validation" / "schemas" / "manifest.schema.json"
)


def test_manifest_artifact_enum_is_pinned() -> None:
    """The taxonomy is a published contract -- changing it must be a deliberate edit here."""
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    assert set(schema["properties"]["artifact"]["enum"]) == EXPECTED_ARTIFACTS


def test_code_derives_artifact_types_from_the_schema() -> None:
    """Code must read the taxonomy from the schema, never restate it.

    A `command` artifact type outlived the v3 migration because three modules each
    held their own copy. ARTIFACT_TYPES is derived, so that cannot recur.
    """
    assert ARTIFACT_TYPES == frozenset(EXPECTED_ARTIFACTS)
