"""Script integrity (DET-2) is a registry check, so `registry_check=False` skips it like freshness."""

from __future__ import annotations

import shutil
from pathlib import Path

import yaml
from conftest import baseline_policy

from chock.validation.engine import validate_artifact
from chock.validation.report import Report

_GUARD = '#!/usr/bin/env python3\n"""Refuse nothing; the shape is what is under test."""\n\nraise SystemExit(0)\n'


def _production_rule_with_script(tmp_path: Path) -> Path:
    """A production rule carrying a commit script: DET-2 applies to it since a rule's hook is hashed."""
    source = baseline_policy("protect-commit-privacy")
    policy_dir = tmp_path / ".agents" / "policies" / source.name
    shutil.copytree(source, policy_dir)
    manifest = yaml.safe_load((policy_dir / "manifest.yaml").read_text(encoding="utf-8"))
    manifest["enforcement"] = "block"
    manifest["hook"] = {"script": {"on": ["commit"]}}
    manifest["lifecycle"] = {**manifest.get("lifecycle", {}), "status": "production"}
    (policy_dir / "manifest.yaml").write_text(yaml.safe_dump(manifest), encoding="utf-8")
    guard = policy_dir / "implementations" / f"{source.name}-pre-commit.py"
    guard.write_text(_GUARD, encoding="utf-8")
    guard.chmod(0o755)
    return policy_dir


def _integrity(policy_dir: Path, root: Path, *, registry_check: bool) -> list[str]:
    report = Report()
    validate_artifact("rule", policy_dir, "agnostic", report, root, registry_check=registry_check)
    return [f.message for f in report.errors if f.check == "script_integrity"]


def test_no_registry_check_skips_script_integrity(tmp_path: Path) -> None:
    """A catalog validating its source policies has no registry for them; asking to skip must skip."""
    policy_dir = _production_rule_with_script(tmp_path)
    assert _integrity(policy_dir, tmp_path, registry_check=False) == []


def test_the_registry_check_still_demands_the_entry(tmp_path: Path) -> None:
    """The default keeps DET-2: a production script with no registry is still refused."""
    policy_dir = _production_rule_with_script(tmp_path)
    assert _integrity(policy_dir, tmp_path, registry_check=True), "DET-2 must still run by default"
