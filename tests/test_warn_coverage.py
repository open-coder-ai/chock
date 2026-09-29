"""A policy whose only mechanism warns is not credited as enforcing; an ask is."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from chock.compile.actions import credited_surfaces
from chock.compile.compiler import compile_policy
from chock.compile.surfaces import Surface


def _manifest(action: str, *, on: list[str], artifact: str = "hook") -> dict:
    manifest = {
        "id": "gated",
        "name": "gated",
        "version": "0.0.1",
        "description": "test",
        "artifact": artifact,
        "enforcement": "block",
        "effects": ["read_only"],
        "approval": {"required": False},
        "provenance": {"author": "a", "source_repo": "https://example.com", "license": "Apache-2.0"},
        "lifecycle": {"status": "draft"},
        "security": {"content_instructions": "never-obey"},
        "hook": {
            "gate": {
                "kind": "content_regex",
                "on": on,
                "action": action,
                "message": "no BAD",
                "params": {"content_pattern": "BAD"},
            }
        },
    }
    if artifact == "rule":
        manifest["rule"] = {"text": "never(BAD)"}
        del manifest["effects"], manifest["approval"]
    return manifest


def _levels(tmp_path: Path, manifest: dict) -> dict[str, str]:
    policy = tmp_path / ".agents" / "policies" / "gated"
    policy.mkdir(parents=True)
    (policy / "manifest.yaml").write_text(yaml.safe_dump(manifest), encoding="utf-8")
    result = compile_policy(
        policy, targets=[s.value for s in Surface], output_root=tmp_path / ".chock" / "compiled", agents=["claude"]
    )
    return {agent: cell["level"] for agent, cell in result.coverage["gated"].items()}


@pytest.mark.parametrize("action", ["block", "ask"])
def test_a_gate_that_refuses_is_enforced_at_commit(tmp_path: Path, action: str) -> None:
    assert _levels(tmp_path, _manifest(action, on=["commit"]))["claude"] == "enforced-at-commit"


def test_a_gate_that_only_warns_is_not_enforcing(tmp_path: Path) -> None:
    assert _levels(tmp_path, _manifest("warn", on=["commit"]))["claude"] in {"advisory", "none"}


def test_a_warn_gate_with_an_ambient_rule_reads_advisory(tmp_path: Path) -> None:
    levels = _levels(tmp_path, _manifest("warn", on=["commit", "push"], artifact="rule"))
    assert levels["claude"] == "advisory"


def test_a_tool_use_warn_is_not_credited_either(tmp_path: Path) -> None:
    """A tool_use warn compiles pre-tool-use and stop fragments; none of that refuses anything."""
    assert _levels(tmp_path, _manifest("warn", on=["commit", "tool_use"]))["claude"] in {"advisory", "none"}


def test_the_credit_rule_is_only_about_warn() -> None:
    every = set(Surface)
    assert credited_surfaces(every, _manifest("block", on=["commit"]), has_guard=False) == every
    assert credited_surfaces(every, _manifest("ask", on=["commit"]), has_guard=False) == every
    kept = credited_surfaces(every, _manifest("warn", on=["commit"]), has_guard=False)
    assert not kept & {Surface.GIT_HOOK, Surface.CI_GATE, Surface.STOP, Surface.PRE_TOOL_USE, Surface.AGENT_HOOKS}
    assert Surface.AMBIENT_RULE in kept
    guarded = credited_surfaces(every, _manifest("warn", on=["commit"]), has_guard=True)
    assert Surface.PRE_TOOL_USE in guarded
    assert Surface.GIT_HOOK not in guarded
