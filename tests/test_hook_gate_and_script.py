"""A hook may carry both a gate and a script: the same control on its tool_use and git surfaces."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
import yaml
from conftest import baseline_policy

from chock.compile.compiler import compile_policy
from chock.compile.surfaces import Surface
from chock.validation.engine import validate_artifact
from chock.validation.report import Report

_GUARD = '#!/usr/bin/env python3\n"""Allow everything; the wiring is what is under test."""\n\nraise SystemExit(0)\n'
_GATE = {
    "kind": "content_regex",
    "on": ["tool_use"],
    "action": "block",
    "message": "the marker must survive",
    "params": {"content_pattern": "ERASED"},
}


def _policy(tmp_path: Path, *, gate_on: list[str], script_on: list[str], ship: tuple[str, ...]) -> Path:
    """A real baseline rule, given a hook holding both halves."""
    source = baseline_policy("protect-commit-privacy")
    policy_dir = tmp_path / ".agents" / "policies" / source.name
    shutil.copytree(source, policy_dir)
    manifest = yaml.safe_load((policy_dir / "manifest.yaml").read_text(encoding="utf-8"))
    manifest["enforcement"] = "block"
    manifest["hook"] = {"gate": {**_GATE, "on": gate_on}, "script": {"on": script_on}}
    (policy_dir / "manifest.yaml").write_text(yaml.safe_dump(manifest), encoding="utf-8")
    for segment in ship:
        guard = policy_dir / "implementations" / f"{source.name}-{segment}.py"
        guard.parent.mkdir(exist_ok=True)
        guard.write_text(_GUARD, encoding="utf-8")
    return policy_dir


def _errors(policy_dir: Path, tmp_path: Path) -> list[str]:
    report = Report()
    validate_artifact("rule", policy_dir, "agnostic", report, tmp_path, registry_check=False)
    return [f"{f.check}: {f.message}" for f in report.errors]


def test_the_validator_accepts_a_hook_with_both(tmp_path: Path) -> None:
    policy_dir = _policy(tmp_path, gate_on=["tool_use"], script_on=["commit"], ship=("pre-commit",))
    assert _errors(policy_dir, tmp_path) == []


def test_det5_still_binds_the_script_beside_a_gate(tmp_path: Path) -> None:
    policy_dir = _policy(tmp_path, gate_on=["tool_use"], script_on=["commit"], ship=())
    assert any("manifest_script_events" in e and "ships no" in e for e in _errors(policy_dir, tmp_path))


def test_a_gate_and_a_script_may_not_share_a_git_event(tmp_path: Path) -> None:
    """Both would claim the one git-pre-commit shim; one would silently lose."""
    policy_dir = _policy(tmp_path, gate_on=["commit", "tool_use"], script_on=["commit"], ship=("pre-commit",))
    assert any("both run at 'commit'" in e for e in _errors(policy_dir, tmp_path))


def test_the_compiler_emits_the_script_shim_and_the_tool_use_gate(tmp_path: Path) -> None:
    policy_dir = _policy(tmp_path, gate_on=["tool_use"], script_on=["commit"], ship=("pre-commit",))
    output_root = tmp_path / ".chock" / "compiled"
    result = compile_policy(policy_dir, output_root=output_root)

    base = output_root / policy_dir.name
    assert (base / "git-hook" / "git-pre-commit.sh").is_file()
    assert not (base / "git-hook" / "gate.json").exists(), "a tool_use-only gate has no git hook"
    assert json.loads((base / "pre-tool-use" / "gate.json").read_text(encoding="utf-8"))["on"] == ["tool_use"]
    assert result.artifacts[Surface.GIT_HOOK.value]
    assert result.artifacts[Surface.PRE_TOOL_USE.value]


def test_a_gate_on_commit_and_a_script_on_push_both_reach_the_git_hook(tmp_path: Path) -> None:
    policy_dir = _policy(tmp_path, gate_on=["commit", "tool_use"], script_on=["push"], ship=("pre-push",))
    output_root = tmp_path / ".chock" / "compiled"
    compile_policy(policy_dir, targets=[Surface.GIT_HOOK.value], output_root=output_root)

    hook_dir = output_root / policy_dir.name / "git-hook"
    assert {p.name for p in hook_dir.iterdir()} >= {"gate.json", "git-pre-commit.sh", "git-pre-push.sh"}
    assert "gate.json" in (hook_dir / "git-pre-commit.sh").read_text(encoding="utf-8")
    assert "implementations" in (hook_dir / "git-pre-push.sh").read_text(encoding="utf-8")


def test_coverage_credits_the_git_hook_and_no_more(tmp_path: Path) -> None:
    """The script backs commit; an agent with no installed tool_use hook is not credited beyond that."""
    policy_dir = _policy(tmp_path, gate_on=["tool_use"], script_on=["commit"], ship=("pre-commit",))
    result = compile_policy(policy_dir, output_root=tmp_path / ".chock" / "compiled", agents=["claude"])
    cell = result.coverage[policy_dir.name]["claude"]
    assert cell["level"] in {"enforced-at-commit", "enforceable", "best-effort", "fail-to-ask"}
    assert cell["level"] != "enforced", cell


@pytest.mark.parametrize("shape", ["gate", "script"])
def test_either_half_alone_is_still_valid(tmp_path: Path, shape: str) -> None:
    policy_dir = _policy(tmp_path, gate_on=["tool_use"], script_on=["commit"], ship=("pre-commit",))
    path = policy_dir / "manifest.yaml"
    manifest = yaml.safe_load(path.read_text(encoding="utf-8"))
    if shape == "gate":
        del manifest["hook"]["script"]
        (policy_dir / "implementations" / f"{policy_dir.name}-pre-commit.py").unlink()
    else:
        del manifest["hook"]["gate"]
    path.write_text(yaml.safe_dump(manifest), encoding="utf-8")
    assert _errors(policy_dir, tmp_path) == []
