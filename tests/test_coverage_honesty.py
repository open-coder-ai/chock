"""Coverage must report what is enforced, not what an agent could support.

`coverage.json` is the framework's central claim about itself, and it was wrong: 14 of 15
policies reported `enforced` -- documented as "a hard, pre-execution control" -- including
advise-only rules with no gate of any kind.

Two causes, independent:

  `coverage_level` asked only whether the policy's target surfaces were a subset of the
  agent's supported ones. It never checked whether a gate existed or whether anything was
  installed, so it measured agent capability.

  The compiler records a key per attempted surface, including emitters that produced
  nothing, so a policy was credited with surfaces it never emitted to.

Nothing in the suite covered any of this before, which is how it stayed wrong. For a
governance tool, overstating its own enforcement is the failure that discredits the rest.
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from chock.compile.compiler import compile_policy
from chock.compile.surfaces import SURFACE_AGENTS, Surface, coverage_level
from chock.scaffold.adapters import CHOCK_AGENT

FRAMEWORK_ROOT = Path(__file__).resolve().parents[1]


def _write(policy_dir: Path, manifest: dict) -> Path:
    policy_dir.mkdir(parents=True, exist_ok=True)
    (policy_dir / "manifest.yaml").write_text(yaml.safe_dump(manifest), encoding="utf-8")
    return policy_dir


def _base(policy_id: str) -> dict:
    return {
        "id": policy_id,
        "name": policy_id,
        "version": "0.0.1",
        "description": "test",
        "provenance": {
            "author": "a",
            "source_repo": "https://example.com",
            "license": "Apache-2.0",
            "trust_tier": "sandbox",
        },
        "lifecycle": {"status": "draft"},
        "security": {"content_instructions": "never-obey"},
    }


def _compile(tmp_path: Path, manifest: dict) -> str:
    policy_dir = _write(tmp_path / ".agents" / "policies" / manifest["id"], manifest)
    result = compile_policy(
        policy_dir, targets=[s.value for s in Surface], output_root=tmp_path / ".chock" / "compiled"
    )
    return result.coverage[manifest["id"]]["claude"]


def test_advise_only_rule_is_advisory_not_enforced(tmp_path: Path) -> None:
    """The headline defect: a rule with no gate claimed a hard pre-execution control."""
    manifest = {**_base("advice"), "artifact": "rule", "enforcement": "advise", "rule": {"text": "be careful"}}
    assert _compile(tmp_path, manifest) == "advisory"


def test_hook_with_a_real_gate_is_enforced_at_commit(tmp_path: Path) -> None:
    manifest = {
        **_base("guard"),
        "artifact": "hook",
        "enforcement": "block",
        "effects": ["read_only"],
        "approval": {"required": False},
        "hook": {
            "gate": {
                "kind": "forbidden_ref",
                "on": ["commit"],
                "action": "block",
                "message": "blocked",
                "params": {"refs": ["main"]},
            }
        },
    }
    assert _compile(tmp_path, manifest) == "enforced-at-commit"


def test_surfaces_that_emit_nothing_do_not_count() -> None:
    """An emitter returning no files must not raise the coverage claim."""
    assert coverage_level(set(), "claude") == "none"
    assert coverage_level({Surface.AMBIENT_RULE}, "claude") == "advisory"


def test_pre_tool_use_alone_is_not_enforced() -> None:
    """A compiled fragment that nothing installed enforces nothing.

    The flag is the switch, so the claim cannot get ahead of the mechanism. The compiler
    derives it from .claude/settings.json rather than taking anyone's word for it.
    """
    assert coverage_level({Surface.PRE_TOOL_USE}, "claude") == "none"
    # claude_code's PreToolUse is FAIL_OPEN (agentseam.matrix_data) -- installed, it reads
    # `best-effort`, never a flat `enforced` (owner decision #9).
    assert coverage_level({Surface.PRE_TOOL_USE}, "claude", pre_tool_use_installed=True) == "best-effort"


def test_unsupported_agent_reports_none() -> None:
    assert coverage_level({Surface.GIT_HOOK}, "no-such-agent") == "none"


def test_every_agent_we_write_a_wrapper_for_has_surfaces() -> None:
    """The two tables must name the same agents, or an adopter is told a lie.

    `init --agents tabnine` wrote `guidelines.md` and then reported every policy as
    `unsupported` on tabnine, because SURFACE_AGENTS listed 11 agents while AGENT_FILES
    wrote 13. The wrapper is an ambient rule by construction -- that is all it is -- so an
    agent with a wrapper and no surfaces is a bookkeeping gap, not an honest disclaimer.

    Understating coverage is a milder failure than overstating it, but it is the same
    failure: the number does not describe the repo.
    """
    assert set(CHOCK_AGENT) == set(SURFACE_AGENTS)


def test_a_wrapper_agent_gets_at_least_the_ambient_rule() -> None:
    """Surfaces are per-agent, but the wrapper is the floor: everyone with one reads rules."""
    for agent in CHOCK_AGENT:
        assert Surface.AMBIENT_RULE in SURFACE_AGENTS[agent], f"{agent} has a wrapper but no ambient rule"
        assert coverage_level({Surface.AMBIENT_RULE}, agent) == "advisory"


def test_repo_coverage_matches_actual_enforcement() -> None:
    """End to end on this repo: every enforcement claim names its real witness.

    `enforced-at-commit` is a git-hook claim, so it requires the compiled gate.
    `enforced` is a pre-execution in-agent claim, so it requires the policy's fragment to
    be INSTALLED in that agent's committed hook config -- a compiled fragment nothing
    installed is the exact overclaim this test exists to prevent. (The original version
    demanded a git-hook gate for every claim; that was right until this repo's settings
    became committed and guard-script policies honestly reached `enforced` without one.)
    """
    from chock.hooks.agenthooks_install import installed_agent_hooks_policy_ids
    from chock.hooks.cursor_install import installed_cursor_policy_ids
    from chock.hooks.pretooluse_install import installed_pretooluse_policy_ids

    coverage = json.loads((FRAMEWORK_ROOT / ".chock" / "coverage.json").read_text(encoding="utf-8"))
    compiled = FRAMEWORK_ROOT / ".chock" / "compiled"
    agent_hooks_witness = installed_agent_hooks_policy_ids(FRAMEWORK_ROOT)
    witnesses = {
        "claude": installed_pretooluse_policy_ids(FRAMEWORK_ROOT),
        "cursor": installed_cursor_policy_ids(FRAMEWORK_ROOT),
        "copilot": agent_hooks_witness,
        "vscode": agent_hooks_witness,
    }

    # Agent-hook levels (owner decision #9): whichever of agentseam's honest per-agent
    # words PRE_TOOL_USE/AGENT_HOOKS earns once installed -- `enforced` is only one of them
    # (claude_code's own PreToolUse is FAIL_OPEN, so it reads `best-effort`, never
    # `enforced`), but every one of them still requires the same install witness.
    AGENT_HOOK_LEVELS = {"enforced", "enforceable", "best-effort"}

    for policy_id, agents in coverage.items():
        for agent, level in agents.items():
            if level in (None, "disabled", "advisory", "none", "detect"):
                continue
            if level == "enforced-at-commit":
                gate = compiled / policy_id / "git-hook" / "gate.json"
                ci = compiled / policy_id / "ci-gate" / "gate.json"
                assert gate.exists() or ci.exists(), (
                    f"{policy_id} claims '{level}' on {agent} but compiled no commit-time gate"
                )
            elif level in AGENT_HOOK_LEVELS:
                assert policy_id in witnesses.get(agent, set()), (
                    f"{policy_id} claims '{level}' on {agent} but its fragment is not installed there"
                )
