"""Tests for structural manifest validation rules (errors)."""

from __future__ import annotations

from pathlib import Path

import yaml

from chock.manifest import load_manifest
from chock.validation.checks_manifest_schema import check_manifest_schema
from chock.validation.report import Report


def _manifest_dir(tmp_path: Path, policy_id: str, data: dict) -> Path:
    policy_dir = tmp_path / policy_id
    policy_dir.mkdir(parents=True)
    (policy_dir / "manifest.yaml").write_text(yaml.safe_dump(data), encoding="utf-8")
    return policy_dir


def _codes(report: Report) -> set[str]:
    return {f.check for f in report.errors}


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
        "trust_tier": "community",
    },
    "lifecycle": {"status": "draft"},
    "security": {"content_instructions": "never-obey"},
}


def test_manifest_id_folder(tmp_path: Path) -> None:
    """Rule 1: manifest id must match the folder name."""
    policy_dir = _manifest_dir(tmp_path, "test-rule", {**MINIMAL_RULE, "id": "wrong-id"})
    report = Report()
    manifest, _ = load_manifest(policy_dir)
    check_manifest_schema(policy_dir, manifest, "rule", report)
    assert "manifest_id_folder" in _codes(report)


def test_manifest_payload(tmp_path: Path) -> None:
    """Rule 2: exactly one payload must match artifact."""
    data = {**MINIMAL_RULE, "rule": {"text": "never(x): y"}, "skill": {"skill_type": "nl"}}
    policy_dir = _manifest_dir(tmp_path, "test-rule", data)
    report = Report()
    manifest, _ = load_manifest(policy_dir)
    check_manifest_schema(policy_dir, manifest, "rule", report)
    assert "manifest_payload" in _codes(report)


def test_manifest_block_needs_gate_no_gate(tmp_path: Path) -> None:
    """Rule 3: block/verify hook requires a gate definition."""
    data = {**MINIMAL_RULE, "artifact": "hook", "enforcement": "block", "hook": {}}
    policy_dir = _manifest_dir(tmp_path, "test-hook", data)
    report = Report()
    manifest, _ = load_manifest(policy_dir)
    check_manifest_schema(policy_dir, manifest, "hook", report)
    assert "manifest_block_needs_gate" in _codes(report)


def test_manifest_gate_params_unknown_kind(tmp_path: Path) -> None:
    """Rule 4: hook.gate.kind must be a known kind."""
    data = {
        **MINIMAL_RULE,
        "id": "test-hook",
        "name": "Test Hook",
        "artifact": "hook",
        "enforcement": "block",
        "hook": {
            "gate": {
                "kind": "unknown_kind",
                "on": ["commit"],
                "action": "block",
                "message": "blocked",
                "params": {},
            }
        },
    }
    policy_dir = _manifest_dir(tmp_path, "test-hook", data)
    report = Report()
    manifest, _ = load_manifest(policy_dir)
    check_manifest_schema(policy_dir, manifest, "hook", report)
    assert "manifest_gate_params" in _codes(report)


def test_manifest_gate_params_missing_required(tmp_path: Path) -> None:
    """Rule 4: hook.gate.params must conform to the kind's param schema."""
    data = {
        **MINIMAL_RULE,
        "id": "test-hook",
        "name": "Test Hook",
        "artifact": "hook",
        "enforcement": "block",
        "hook": {
            "gate": {
                "kind": "content_regex",
                "on": ["commit"],
                "action": "block",
                "message": "blocked",
                "params": {"scan": "added_lines"},
            }
        },
    }
    policy_dir = _manifest_dir(tmp_path, "test-hook", data)
    report = Report()
    manifest, _ = load_manifest(policy_dir)
    check_manifest_schema(policy_dir, manifest, "hook", report)
    assert "manifest_gate_params" in _codes(report)


def test_manifest_self_dependency(tmp_path: Path) -> None:
    """Rule 5: a policy must not list itself in dependencies.policies."""
    data = {
        **MINIMAL_RULE,
        "dependencies": {"policies": [{"id": "test-rule"}]},
    }
    policy_dir = _manifest_dir(tmp_path, "test-rule", data)
    report = Report()
    manifest, _ = load_manifest(policy_dir)
    check_manifest_schema(policy_dir, manifest, "rule", report)
    assert "manifest_self_dependency" in _codes(report)


def test_manifest_self_conflict(tmp_path: Path) -> None:
    """Rule 6: a policy must not list itself in conflicts_with."""
    data = {
        **MINIMAL_RULE,
        "conflicts_with": [{"id": "test-rule", "reason": "testing"}],
    }
    policy_dir = _manifest_dir(tmp_path, "test-rule", data)
    report = Report()
    manifest, _ = load_manifest(policy_dir)
    check_manifest_schema(policy_dir, manifest, "rule", report)
    assert "manifest_self_conflict" in _codes(report)


def test_manifest_bundle_assets(tmp_path: Path) -> None:
    """Rule 7: bundle.shared_assets must resolve within the policy directory."""
    data = {
        **MINIMAL_RULE,
        "bundle": {"id": "test-bundle", "shared_assets": ["missing.txt", "../outside.txt"]},
    }
    policy_dir = _manifest_dir(tmp_path, "test-rule", data)
    (tmp_path / "outside.txt").write_text("outside", encoding="utf-8")
    report = Report()
    manifest, _ = load_manifest(policy_dir)
    check_manifest_schema(policy_dir, manifest, "rule", report)
    assert "manifest_bundle_assets" in _codes(report)


def test_manifest_workflow_uses(tmp_path: Path) -> None:
    """Rule 8: workflow steps must use a declared policy dependency."""
    data = {
        **MINIMAL_RULE,
        "id": "test-workflow",
        "name": "Test Workflow",
        "artifact": "workflow",
        "workflow": {
            "effects": ["read_only"],
            "approval": {"required": False},
            "control": "deterministic",
            "steps": [{"id": "step1", "uses": "undeclared-policy"}],
        },
    }
    policy_dir = _manifest_dir(tmp_path, "test-workflow", data)
    report = Report()
    manifest, _ = load_manifest(policy_dir)
    check_manifest_schema(policy_dir, manifest, "workflow", report)
    assert "manifest_workflow_uses" in _codes(report)
