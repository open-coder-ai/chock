"""DET-6: a guard's or an event script's Edit/Write door is a declared gate, never an implied one."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import yaml
from conftest import baseline_policy

from chock.validation.checks_write_path import NEVER_MATCHES, check_write_path_pairing
from chock.validation.engine import validate_artifact
from chock.validation.report import Report

POLICY_ID = "protect-things"
CATEGORY = "manifest_write_path"
PATHS = r"(^|/)\.github/workflows/"
PATH_GATE = {
    "kind": "content_regex",
    "on": ["tool_use"],
    "action": "block",
    "message": "CI workflows are changed by a person; propose the edit instead",
    "params": {"scan": "added_lines", "forbidden_path_regex": PATHS, "content_pattern": NEVER_MATCHES},
}
CONTENT_GATE = {
    "kind": "content_regex",
    "on": ["commit"],
    "action": "block",
    "message": "remove the marker",
    "params": {"scan": "added_lines", "content_pattern": "HAND_EDITED"},
}
SCRIPT_GATE = {
    "kind": "script",
    "on": ["tool_use"],
    "action": "block",
    "message": "fix the regression the script names",
    "params": {"script": f"{POLICY_ID}-write.py"},
}
_SUITE = {
    "suite": {
        "id": f"{POLICY_ID}-tests-v1",
        "policy_id": POLICY_ID,
        "version_constraint": ">=0.0.1",
        "maintainer": "t",
        "primary_metric": "pass_rate",
        "metrics": {"pass_rate": {"direction": "higher_is_better", "threshold": 1.0}},
        "cases": [
            {"id": f"tc-00{n}", "category": c, "prompt": "edit the workflow", "expect": "refuses"}
            for n, c in enumerate(("trigger", "negative_trigger", "behavior"), 1)
        ],
    }
}
_EXIT0 = '#!/usr/bin/env python3\n"""Allow; the shape is what is under test."""\n\nraise SystemExit(0)\n'


def _manifest(hook: dict) -> dict:
    return {
        "id": POLICY_ID,
        "name": "Protect Things",
        "version": "0.0.1",
        "description": "trigger: editing protected files. avoid: unreviewed edits.",
        "artifact": "rule",
        "enforcement": "block",
        "rule": {"text": "never(edit): protected files\n"},
        "hook": hook,
        "provenance": {
            "author": "t",
            "source_repo": "https://example.invalid/t",
            "license": "Apache-2.0",
            "trust_tier": "community",
        },
        "lifecycle": {"status": "draft"},
        "security": {"content_instructions": "never-obey"},
    }


def _policy(tmp_path: Path, manifest: dict, *files: str) -> Path:
    policy = tmp_path / ".agents" / "policies" / POLICY_ID
    (policy / "implementations").mkdir(parents=True)
    (policy / "manifest.yaml").write_text(yaml.safe_dump(manifest), encoding="utf-8")
    (policy / "evals").mkdir()
    (policy / "evals" / "suite.yaml").write_text(yaml.safe_dump(_SUITE), encoding="utf-8")
    for name in files:
        (policy / "implementations" / name).write_text(_EXIT0, encoding="utf-8")
    return policy


def _pairing(tmp_path: Path, hook: dict, *files: str) -> list[str]:
    manifest = _manifest(hook)
    report = Report()
    check_write_path_pairing(_policy(tmp_path, manifest, *files), manifest, "rule", report)
    assert all(f.check == CATEGORY for f in [*report.errors, *report.warnings, *report.infos])
    return [f.message for f in report.errors]


def _validate(tmp_path: Path, hook: dict, *files: str) -> list[str]:
    policy = _policy(tmp_path, _manifest(hook), *files)
    report = Report()
    validate_artifact("rule", policy, "agnostic", report, tmp_path, registry_check=False)
    return [f"{f.check}: {f.message}" for f in report.errors]


GUARD = f"{POLICY_ID}.py"
PRE_COMMIT = f"{POLICY_ID}-pre-commit.py"


@pytest.mark.parametrize(
    ("hook", "files"),
    [
        ({"gate": PATH_GATE}, (GUARD,)),
        ({"gate": {**PATH_GATE, "on": ["commit", "tool_use"]}}, (f"{POLICY_ID}.sh",)),
        ({"script": {"on": ["commit"]}}, (PRE_COMMIT,)),
        ({"gate": {**PATH_GATE, "on": ["commit"]}}, ()),
        ({"gate": CONTENT_GATE}, (GUARD,)),
        ({"script": {"on": ["push"]}}, (GUARD, f"{POLICY_ID}-pre-push.py")),
        ({"script": {"on": ["commit"]}, "gate": SCRIPT_GATE}, (PRE_COMMIT, f"{POLICY_ID}-write.py")),
    ],
    ids=[
        "guard-plus-path-gate",
        "sh-guard-plus-path-gate-at-commit-too",
        "script-only",
        "path-gate-only-at-commit",
        "guard-plus-content-gate",
        "guard-plus-push-script",
        "event-script-plus-script-gate",
    ],
)
def test_valid_shapes_raise_nothing(tmp_path: Path, hook: dict, files: tuple[str, ...]) -> None:
    assert _pairing(tmp_path / "direct", hook, *files) == []
    errors = _validate(tmp_path / "engine", hook, *files)
    assert errors == []


@pytest.mark.parametrize("event", ["tool_use", "tool_call", "stop", "ci"])
def test_a_script_cannot_claim_an_agent_or_ci_event(tmp_path: Path, event: str) -> None:
    """A git-hook script never runs in the agent or CI; the error names the gate that does."""
    found = _pairing(tmp_path, {"script": {"on": ["commit", event]}}, PRE_COMMIT)
    assert len(found) == 1, found
    assert f"'{event}'" in found[0]
    assert "kind: script" in found[0]
    assert "forbidden_path_regex" in found[0]


def test_the_validator_reports_the_script_event_with_the_remedy(tmp_path: Path) -> None:
    """The schema's enum error alone says what is wrong, not what to write instead."""
    errors = _validate(tmp_path, {"script": {"on": ["tool_use"]}})
    assert any(e.startswith(f"{CATEGORY}: ") and "kind: script" in e for e in errors), errors


def test_a_path_gate_with_no_path_can_never_refuse(tmp_path: Path) -> None:
    params = {"scan": "added_lines", "content_pattern": NEVER_MATCHES}
    found = _pairing(tmp_path, {"gate": {**PATH_GATE, "params": params}})
    assert len(found) == 1, found
    assert "never" in found[0]
    assert "forbidden_path_regex" in found[0]


@pytest.mark.parametrize("paths", ["", None])
def test_an_empty_path_regex_is_no_path(tmp_path: Path, paths: str | None) -> None:
    """The runner ignores an empty or null regex; neither is a path gate."""
    params = {"scan": "added_lines", "content_pattern": NEVER_MATCHES, "forbidden_path_regex": paths}
    found = _pairing(tmp_path, {"gate": {**PATH_GATE, "params": params}})
    assert any("forbidden_path_regex" in f for f in found), found


@pytest.mark.parametrize("on", [["commit"], ["push"], ["commit", "push"], ["tool_call"]])
def test_a_guard_with_a_path_gate_off_the_write_path_is_an_error(tmp_path: Path, on: list[str]) -> None:
    """The guard sees shell commands only; its path gate is the Edit/Write door or nothing."""
    found = _pairing(tmp_path, {"gate": {**PATH_GATE, "on": on}}, GUARD)
    assert len(found) == 1, found
    assert f"implementations/{GUARD}" in found[0]
    assert "tool_use" in found[0]


def test_the_legacy_guard_name_counts_as_a_guard(tmp_path: Path) -> None:
    """block-destructive-commands ships its guard under the legacy name; it pairs the same."""
    manifest = _manifest({"gate": {**PATH_GATE, "on": ["commit"]}})
    manifest["id"] = "block-destructive-commands"
    policy = tmp_path / "block-destructive-commands"
    (policy / "implementations").mkdir(parents=True)
    (policy / "implementations" / "block-destructive.sh").write_text("exit 0\n", encoding="utf-8")
    report = Report()
    check_write_path_pairing(policy, manifest, "rule", report)
    assert [f.message for f in report.errors if "block-destructive.sh" in f.message]


def test_an_advise_policy_is_held_to_the_same_shape(tmp_path: Path) -> None:
    """The gate shape is checked whatever the enforcement claim; a dead gate is dead either way."""
    manifest = {**_manifest({"gate": {**PATH_GATE, "on": ["commit"]}}), "enforcement": "advise"}
    report = Report()
    check_write_path_pairing(_policy(tmp_path, manifest, GUARD), manifest, "rule", report)
    assert report.errors


@pytest.mark.parametrize("hook", [{}, {"gate": None}, {"script": None}, {"gate": {"kind": "content_regex"}}])
def test_partial_hooks_are_left_to_the_schema(tmp_path: Path, hook: dict) -> None:
    """Missing keys are the schema's findings; this check must not crash on them."""
    assert _pairing(tmp_path, hook, GUARD) == []


def test_the_shipped_pairing_policy_validates_clean(tmp_path: Path) -> None:
    """protect-agent-config is the pattern this check describes; it must pass unchanged."""
    source = baseline_policy("protect-agent-config")
    policy = tmp_path / ".agents" / "policies" / source.name
    shutil.copytree(source, policy)
    manifest = yaml.safe_load((policy / "manifest.yaml").read_text(encoding="utf-8"))
    assert manifest["hook"]["gate"]["params"]["content_pattern"] == NEVER_MATCHES
    report = Report()
    check_write_path_pairing(policy, manifest, "rule", report)
    assert [*report.errors, *report.warnings, *report.infos] == []


@pytest.mark.parametrize("pattern", [" (?!) ", "(?!)\n"])
def test_whitespace_around_the_idiom_is_still_the_idiom(tmp_path: Path, pattern: str) -> None:
    params = {"scan": "added_lines", "content_pattern": pattern}
    assert _pairing(tmp_path, {"gate": {**PATH_GATE, "params": params}})


@pytest.mark.parametrize(
    "hook",
    [
        {"script": {"on": [{"a": 1}]}},
        {"script": {"on": [["tool_use"]]}},
        {"script": {"on": "tool_use"}},
        {"gate": {**PATH_GATE, "on": "tool_use"}},
        {"gate": {**PATH_GATE, "params": {"content_pattern": ["(?!)"]}}},
    ],
    ids=["dict-event", "list-event", "string-on", "string-gate-on", "list-pattern"],
)
def test_malformed_shapes_do_not_crash_the_validator(tmp_path: Path, hook: dict) -> None:
    """Wrong types are the schema's or the params check's error; neither new code path may raise."""
    errors = _validate(tmp_path, hook, GUARD, PRE_COMMIT)
    assert any(e.startswith(("schema: ", "manifest_gate_params: ")) for e in errors), errors
    assert not any("lacks tool_use" in e for e in errors), errors
