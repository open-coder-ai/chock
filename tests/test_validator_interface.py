"""Validator interface-rigor checks: effects, schema strictness, naming, DET-3 ack."""

import pytest

import chock.validation as _pkg


def _load_validator():
    return _pkg


validator = _load_validator()


def test_effects_and_approval(tmp_path):
    """Non-none effects require verify/block enforcement and approval wiring."""
    skill_dir = tmp_path / "test-skill"
    skill_dir.mkdir()
    (skill_dir / "manifest.yaml").write_text("id: test-skill\nartifact: skill\n", encoding="utf-8")

    # Missing approval with non-none effects.
    manifest = {"effects": ["writes_external"], "enforcement": "verify"}
    report = validator.Report()
    validator.check_effects_and_approval(skill_dir, manifest, "skill", report)
    assert any(f.check == "effects" and "approval" in f.message for f in report.errors)

    # Wrong enforcement with non-none effects.
    manifest = {"effects": ["writes_external"], "enforcement": "advise", "approval": {"required": True}}
    report = validator.Report()
    validator.check_effects_and_approval(skill_dir, manifest, "skill", report)
    assert any(f.check == "effects" and "enforcement" in f.message for f in report.errors)

    # Valid non-none effects.
    manifest = {"effects": ["writes_external"], "enforcement": "verify", "approval": {"required": True}}
    report = validator.Report()
    validator.check_effects_and_approval(skill_dir, manifest, "skill", report)
    assert not any(f.check == "effects" for f in report.errors)

    # Mixing none with other effects is an error.
    manifest = {"effects": ["none", "writes_external"], "enforcement": "verify", "approval": {"required": True}}
    report = validator.Report()
    validator.check_effects_and_approval(skill_dir, manifest, "skill", report)
    assert any(f.check == "effects" and "mix" in f.message for f in report.errors)

    # [none] is allowed with any enforcement.
    manifest = {"effects": ["none"], "enforcement": "advise"}
    report = validator.Report()
    validator.check_effects_and_approval(skill_dir, manifest, "skill", report)
    assert not any(f.check == "effects" for f in report.errors)


def test_skill_schema_enforces_interface_rigor():
    """INT-1/INT-2: unified manifest schema requires additionalProperties: false and outcome enum for skills."""
    import jsonschema

    v = validator.get_validator("manifest.schema.json")
    valid = {
        "id": "create-foo",
        "name": "Create Foo",
        "version": "0.1.0",
        "description": "Creates foo",
        "artifact": "skill",
        "enforcement": "advise",
        "effects": ["none"],
        "input_schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {"request": {"type": "string", "description": "request"}},
            "required": ["request"],
        },
        "output_schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "outcome": {"type": "string", "enum": ["success", "failure", "needs_handoff"], "description": "outcome"}
            },
            "required": ["outcome"],
        },
        "provenance": {
            "author": "a",
            "source_repo": "https://example.com",
            "created_at": "2026-01-01T00:00:00Z",
            "license": "Apache-2.0",
            "trust_tier": "sandbox",
        },
        "lifecycle": {"status": "draft"},
        "evaluation": {"test_suite_ref": "evals/suite.yaml"},
        "security": {"content_instructions": "never-obey"},
        "skill": {
            "skill_type": "nl",
            "entry": "SKILL.md",
            "effects": ["none"],
        },
    }
    v.validate(instance=valid)

    invalid = valid.copy()
    invalid["output_schema"] = {
        "type": "object",
        "additionalProperties": False,
        "properties": {"result": {"type": "string", "description": "result"}},
        "required": ["result"],
    }
    with pytest.raises(jsonschema.ValidationError):
        v.validate(instance=invalid)

    # Missing skill effects is a schema error for skills.
    missing_effects = valid.copy()
    missing_effects["skill"] = dict(valid["skill"])
    del missing_effects["skill"]["effects"]
    with pytest.raises(jsonschema.ValidationError):
        v.validate(instance=missing_effects)


def test_verb_first_naming_int3(tmp_path):
    """INT-3: warn when a draft/sandbox executing artifact does not start with a verb."""
    skill_dir = tmp_path / "new-artifact"
    skill_dir.mkdir()
    manifest = {
        "id": "new-artifact",
        "artifact": "skill",
        "provenance": {"trust_tier": "sandbox"},
        "lifecycle": {"status": "draft"},
    }
    report = validator.Report()
    validator.check_verb_first_naming(skill_dir, manifest, "skill", report)
    assert any(f.check == "interface" and f.severity == "warning" for f in report.warnings)

    manifest["id"] = "create-foo"
    report = validator.Report()
    validator.check_verb_first_naming(skill_dir, manifest, "skill", report)
    assert not any(f.check == "interface" for f in report.warnings)

    # Rules are exempt.
    manifest["id"] = "new-artifact"
    report = validator.Report()
    validator.check_verb_first_naming(skill_dir, manifest, "rule", report)
    assert not any(f.check == "interface" for f in report.warnings)

    # Grandfathered IDs are exempt.
    manifest["id"] = "chock-init"
    report = validator.Report()
    validator.check_verb_first_naming(skill_dir, manifest, "skill", report)
    assert not any(f.check == "interface" for f in report.warnings)


def test_workflow_requires_handoff_monitoring_and_bounded_fanout(tmp_path):
    """Workflow orchestration requires strong monitoring and handoff contracts."""
    art = tmp_path / "orchestrator"
    art.mkdir()
    manifest = {
        "artifact": "workflow",
        "name": "Orchestrator / Upgrade",
        "dependencies": {"skills": [{"id": "analyze"}], "subagents": [{"id": "repo-agent"}]},
        "composition": {
            "phases": [
                {
                    "id": "analyze",
                    "mode": "fan_out",
                    "source": "input.work_items",
                    "invoke": {"skill": "analyze", "subagent": "repo-agent"},
                    "isolation": {"required": True, "boundary": "assigned_work_item"},
                    "concurrency": {"max_parallel": 3},
                    "failure_policy": "continue_and_record",
                    "result": {"correlation_key": "work_item_id"},
                    "monitoring": {
                        "required": True,
                        "heartbeat": "per_item",
                        "timeout": "10m",
                        "terminal_states": ["success", "failure", "needs_handoff"],
                    },
                }
            ],
            "monitoring": {
                "required": True,
                "progress_fields": ["phase", "status", "outcome", "error"],
                "on_missing_result": "needs_handoff",
            },
            "handoff": {
                "required": True,
                "required_fields": ["work_item_id", "phase", "status", "outcome", "error"],
                "on_failure": "needs_handoff",
            },
        },
    }
    report = validator.Report()
    validator.check_composition_contract(art, manifest, "workflow", report)
    assert not report.errors


def test_workflow_subagent_requires_delegation_scope_and_handoff(tmp_path):
    """Workflow subagents must identify their skill, scope, isolation, and result fields."""
    art = tmp_path / "subagent"
    art.mkdir()
    manifest = {
        "delegates": {"skill": "analyze-work-item"},
        "execution_scope": {
            "input_key": "work_item",
            "repository_key": "repository",
            "isolation": {"required": True, "boundary": "assigned_work_item"},
        },
        "output_schema": {
            "required": ["work_item_id", "phase", "status", "outcome"],
            "properties": {
                "work_item_id": {},
                "phase": {},
                "status": {},
                "outcome": {},
            },
        },
    }
    report = validator.Report()
    validator.check_subagent_contract(art, manifest, "subagent", report)
    assert not report.errors


def test_workflow_rejects_unbounded_or_unmonitored_fanout(tmp_path):
    """Fan-out without isolation, monitoring, or correlation is rejected."""
    art = tmp_path / "orchestrator"
    art.mkdir()
    manifest = {
        "artifact": "workflow",
        "name": "Orchestrator / Upgrade",
        "composition": {
            "phases": [{"id": "analyze", "mode": "fan_out", "failure_policy": "stop"}],
            "monitoring": {"required": False},
            "handoff": {"required": False, "required_fields": [], "on_failure": "stop"},
        },
    }
    report = validator.Report()
    validator.check_composition_contract(art, manifest, "workflow", report)
    assert len(report.errors) >= 5


def test_determinization_reviewed_suppresses_det3(tmp_path):
    """A reviewed acknowledgment silences the DET-3 candidate info."""
    validator = _load_validator()
    art = tmp_path / "art"
    art.mkdir()
    (art / "SKILL.md").write_text("body with ^(feat|fix)/ regex heuristics\n", encoding="utf-8")
    report = validator.Report()
    validator.check_determinization_heuristic(art, {"skill": {"skill_type": "nl"}}, "skill", report)
    assert report.infos  # unacknowledged -> info
    report2 = validator.Report()
    validator.check_determinization_heuristic(
        art, {"skill": {"skill_type": "nl"}, "determinization_reviewed": True}, "skill", report2
    )
    assert not report2.infos
