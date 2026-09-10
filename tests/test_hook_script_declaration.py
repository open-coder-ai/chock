"""A script-backed gate can say what it does, and cannot say it without shipping it."""

from __future__ import annotations

import shutil
from pathlib import Path

import yaml
from conftest import baseline_policy

from chock.compile.compiler import compile_policy
from chock.compile.emitters.git_hook import declared_script_events
from chock.compile.surfaces import Surface
from chock.validation.checks_script_events import check_script_events
from chock.validation.engine import validate_artifact
from chock.validation.report import Report

POLICY_ID = "refuse-erasure"

_GUARD = '#!/usr/bin/env python3\n"""Refuse nothing; the shape is what is under test."""\n\nraise SystemExit(0)\n'


def _manifest(**over: object) -> dict[str, object]:
    base: dict[str, object] = {
        "id": POLICY_ID,
        "name": "Refuse Erasure",
        "version": "0.0.1",
        "description": "trigger: editing marked files. avoid: erasing the marker.",
        "artifact": "rule",
        "enforcement": "block",
        "rule": {"text": "never(erase): MARKER\nprefer: restoring what the element carried\n"},
        "hook": {"script": {"on": ["commit"]}},
        "provenance": {
            "author": "t",
            "created_at": "2026-09-10T00:00:00Z",
            "updated_at": "2026-09-10T00:00:00Z",
            "source_repo": "https://example.invalid/t",
            "license": "Apache-2.0",
            "trust_tier": "community",
        },
        "lifecycle": {"status": "draft"},
        "security": {"content_instructions": "never-obey"},
    }
    base.update(over)
    return base


def _policy(tmp_path: Path, manifest: dict[str, object], *segments: str) -> Path:
    policy_dir = tmp_path / ".agents" / "policies" / POLICY_ID
    (policy_dir / "implementations").mkdir(parents=True)
    (policy_dir / "manifest.yaml").write_text(yaml.safe_dump(manifest), encoding="utf-8")
    (policy_dir / "evals").mkdir()
    (policy_dir / "evals" / "suite.yaml").write_text(
        yaml.safe_dump(
            {
                "suite": {
                    "cases": [
                        {
                            "id": "tc-001",
                            "category": "trigger",
                            "prompt": "erase the MARKER from page.html",
                            "expect": "refuses, naming the marker it would lose",
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )
    for segment in segments:
        guard = policy_dir / "implementations" / f"{POLICY_ID}-{segment}.py"
        guard.write_text(_GUARD, encoding="utf-8")
        guard.chmod(0o755)
    return policy_dir


def _findings(policy_dir: Path, manifest: dict[str, object]) -> list[str]:
    report = Report()
    check_script_events(policy_dir, manifest, "rule", report)
    return [f"{f.check}: {f.message}" for f in report.errors]


def test_a_rule_may_declare_the_script_that_enforces_it(tmp_path: Path) -> None:
    """The point of the change: an existing, valid rule policy gains a script and stays valid.

    Built from a real baseline policy rather than a hand-written manifest, so what passes here
    is the whole validator, not a fixture shaped to satisfy the checks this change touches.
    """
    source = baseline_policy("protect-commit-privacy")
    policy_dir = tmp_path / ".agents" / "policies" / source.name
    shutil.copytree(source, policy_dir)
    manifest = yaml.safe_load((policy_dir / "manifest.yaml").read_text(encoding="utf-8"))
    assert manifest["artifact"] == "rule", "this test needs a rule artifact to add a hook to"

    manifest["enforcement"] = "block"
    manifest["hook"] = {"script": {"on": ["commit"]}}
    (policy_dir / "manifest.yaml").write_text(yaml.safe_dump(manifest), encoding="utf-8")
    guard = policy_dir / "implementations" / f"{source.name}-pre-commit.py"
    guard.write_text(_GUARD, encoding="utf-8")
    guard.chmod(0o755)

    report = Report()
    validate_artifact("rule", policy_dir, "agnostic", report, Path(tmp_path), registry_check=False)

    assert not report.errors, [f"{f.check}: {f.message}" for f in report.errors]


def test_a_declared_event_with_no_script_is_an_error(tmp_path: Path) -> None:
    """Otherwise the compiler wires a hook to a file that is not there."""
    manifest = _manifest()
    policy_dir = _policy(tmp_path, manifest)  # declares commit, ships nothing

    found = _findings(policy_dir, manifest)
    assert any("ships no" in f for f in found), found


def test_a_script_on_disk_that_nothing_declares_is_an_error(tmp_path: Path) -> None:
    """The other drift direction: a policy that looks enforced and is not."""
    manifest = _manifest(hook={"script": {"on": ["commit"]}})
    policy_dir = _policy(tmp_path, manifest, "pre-commit", "pre-push")  # push undeclared

    found = _findings(policy_dir, manifest)
    assert any("does not declare 'push'" in f for f in found), found


def test_the_cross_check_runs_inside_the_validator(tmp_path: Path) -> None:
    """Calling the check directly proves it works; only this proves `chock check` runs it."""
    source = baseline_policy("protect-commit-privacy")
    policy_dir = tmp_path / ".agents" / "policies" / source.name
    shutil.copytree(source, policy_dir)
    manifest = yaml.safe_load((policy_dir / "manifest.yaml").read_text(encoding="utf-8"))
    manifest["enforcement"] = "block"
    manifest["hook"] = {"script": {"on": ["commit"]}}  # declared, and deliberately not shipped
    (policy_dir / "manifest.yaml").write_text(yaml.safe_dump(manifest), encoding="utf-8")

    report = Report()
    validate_artifact("rule", policy_dir, "agnostic", report, Path(tmp_path), registry_check=False)

    assert [f for f in report.errors if f.check == "manifest_script_events"], [
        f"{f.check}: {f.message}" for f in report.errors
    ]


def test_a_policy_with_neither_is_not_its_business(tmp_path: Path) -> None:
    """A rule with no script and no declaration must not be reported about."""
    manifest = _manifest(enforcement="advise")
    del manifest["hook"]
    assert _findings(_policy(tmp_path, manifest), manifest) == []


def test_enforcement_block_no_longer_demands_a_declarative_gate(tmp_path: Path) -> None:
    """The whole reason for the change: manifest_block_needs_gate rejected this shape."""
    manifest = _manifest()
    policy_dir = _policy(tmp_path, manifest, "pre-commit")

    report = Report()
    validate_artifact("rule", policy_dir, "agnostic", report, Path(tmp_path), registry_check=False)

    assert not [f for f in report.errors if f.check == "manifest_block_needs_gate"]


def test_block_with_neither_gate_nor_script_is_still_refused(tmp_path: Path) -> None:
    """The check must still catch a policy claiming enforcement it has not wired."""
    manifest = _manifest()
    del manifest["hook"]
    policy_dir = _policy(tmp_path, manifest)

    report = Report()
    validate_artifact("rule", policy_dir, "agnostic", report, Path(tmp_path), registry_check=False)

    assert [f for f in report.errors if f.check == "manifest_block_needs_gate"]


def test_a_rule_may_not_carry_a_declarative_gate(tmp_path: Path) -> None:
    """Two mechanisms would be two answers to what enforces this policy."""
    manifest = _manifest(
        hook={
            "gate": {
                "kind": "forbidden_ref",
                "on": ["commit"],
                "action": "block",
                "message": "no",
                "params": {"refs": ["main"]},
            }
        }
    )
    policy_dir = _policy(tmp_path, manifest)

    report = Report()
    validate_artifact("rule", policy_dir, "agnostic", report, Path(tmp_path), registry_check=False)

    assert [f for f in report.errors if f.check == "manifest_payload"]


def test_the_declaration_decides_what_is_wired_not_the_directory(tmp_path: Path) -> None:
    """A script the manifest does not declare must not reach a consumer repo's hooks."""
    manifest = _manifest()
    policy_dir = _policy(tmp_path, manifest, "pre-commit", "pre-push")
    output_root = tmp_path / ".chock" / "compiled"

    compile_policy(policy_dir, targets=[Surface.GIT_HOOK.value], output_root=output_root)

    git_hook_dir = output_root / POLICY_ID / "git-hook"
    assert (git_hook_dir / "git-pre-commit.sh").exists()
    assert not (git_hook_dir / "git-pre-push.sh").exists(), "an undeclared event was wired"


def test_a_shipped_script_with_no_declaration_wires_nothing(tmp_path: Path) -> None:
    """Before this change the filename alone wired the hook; now the manifest must say so."""
    manifest = _manifest(enforcement="advise")
    del manifest["hook"]
    policy_dir = _policy(tmp_path, manifest, "pre-commit")
    output_root = tmp_path / ".chock" / "compiled"

    compile_policy(policy_dir, targets=[Surface.GIT_HOOK.value], output_root=output_root)

    assert declared_script_events(manifest) == []
    assert not (output_root / POLICY_ID / "git-hook").exists()
