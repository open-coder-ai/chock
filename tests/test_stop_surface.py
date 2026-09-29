"""The end-of-turn backstop: who gets one, who deliberately does not, and what it is worth.

`stop` exists for exactly what the write path structurally cannot see. A pre-tool hook is
handed the tool call, so a heredoc, a shell redirect or any tool whose write vocabulary
nobody recorded goes past it unread. A turn-end hook is handed nothing and reads the
worktree instead, which is why it catches those -- and why it catches nothing sooner, and
is credited with no coverage at all.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from agentseam import contract, matrix

from chock import vendors
from chock.compile.emitters.in_agent import GATE_FILE, STOP_FRAGMENT, emit_stop
from chock.compile.levels import STOP_TODAY
from chock.compile.surfaces import SURFACE_AGENTS, Surface, coverage_level
from chock.vendors import CHOCK_AGENT

PATTERN = r"AKIA[0-9A-Z]{16}"


def _policy(tmp_path: Path, *, on=("commit", "tool_use"), kind="content_regex", script=False) -> tuple[Path, dict]:
    policy = tmp_path / "policy"
    policy.mkdir(parents=True, exist_ok=True)
    params = {"content_pattern": PATTERN} if kind == "content_regex" else {"refs": ["main"]}
    manifest = {
        "id": "leaky",
        "name": "Leaky",
        "version": "0.0.1",
        "description": "d",
        "artifact": "hook",
        "enforcement": "block",
        "hook": {"gate": {"kind": kind, "on": list(on), "action": "block", "message": "m", "params": params}},
        "provenance": {"author": "t"},
        "lifecycle": {"status": "draft"},
    }
    (policy / "manifest.yaml").write_text(yaml.safe_dump(manifest), encoding="utf-8")
    if script:
        impl = policy / "implementations"
        impl.mkdir(exist_ok=True)
        (impl / "leaky.sh").write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    return policy, manifest


def _emit(tmp_path: Path, policy: Path, manifest: dict) -> dict[str, dict]:
    out = tmp_path / ".chock" / "compiled" / "leaky" / "stop"
    out.mkdir(parents=True, exist_ok=True)
    written = emit_stop(policy, out, manifest)
    return {p.name: json.loads(p.read_text(encoding="utf-8")) for p in written}


# --- membership is asked of the matrix, never typed here ---------------------------------------


def test_membership_is_the_matrix_answer_for_the_turn_end_event() -> None:
    """Not inherited from the pre-tool answer: it is a different question with a different answer."""
    expected = sorted(
        agent
        for agent, vendor in CHOCK_AGENT.items()
        if matrix.can_block(vendor, contract.STOP) and vendors.repo_wirable(vendor)
    )
    assert sorted(STOP_TODAY) == expected
    assert sorted(a for a, s in SURFACE_AGENTS.items() if Surface.STOP in s) == expected


@pytest.mark.parametrize("agent", ["grok", "windsurf"])
def test_an_agent_that_can_only_watch_a_turn_end_gets_no_stop_surface(agent: str) -> None:
    """`detect` is not `block`. A hook that cannot refuse would be a log line sold as a control."""
    assert matrix.enforcement_level(CHOCK_AGENT[agent], contract.STOP) == "detect"
    assert Surface.STOP not in SURFACE_AGENTS[agent]
    assert Surface.PRE_TOOL_USE in SURFACE_AGENTS[agent], "the pre-tool answer is unchanged"


def test_cursor_s_turn_end_is_a_follow_up_and_counts_as_a_stop_surface() -> None:
    """Witnessed on 3.21.18: `stop` honours `followup_message`, so the turn is not held but the
    agent is sent back to the refusal -- best-effort, and a surface worth wiring."""
    assert matrix.enforcement_level("cursor", contract.STOP) == "best-effort"
    assert "cursor" in vendors.stop_vendors()
    assert Surface.STOP in SURFACE_AGENTS["cursor"]


@pytest.mark.parametrize("agent", ["copilot", "vscode"])
def test_the_owned_hooks_file_vendors_are_admitted_now_their_stop_key_is_witnessed(agent: str) -> None:
    """Their `Stop` key in chock's own `.github/hooks/chock.json` fired in VS Code agent mode (2026-09-28)."""
    vendor = CHOCK_AGENT[agent]
    assert matrix.can_block(vendor, contract.STOP)
    assert vendor in vendors.AGENT_HOOKS_VENDORS
    assert vendor in vendors.stop_vendors()
    assert vendors.stop_event(vendor) == "Stop", "registered under Stop alone: agentStop fires beside it"
    assert Surface.STOP in SURFACE_AGENTS[agent]


# --- what it emits, and for whom -----------------------------------------------------------------


def test_every_stop_vendor_gets_a_fragment_and_they_all_run_one_gate(tmp_path: Path) -> None:
    """The count comes from the derived vendor set, so a vendor gaining the event gains a file."""
    policy, manifest = _policy(tmp_path)
    emitted = _emit(tmp_path, policy, manifest)

    assert GATE_FILE in emitted
    assert len(emitted) == len(vendors.stop_vendors()) + 1
    assert STOP_FRAGMENT in emitted, "claude's fragment is named apart from its two pre-tool ones"
    for vendor in vendors.stop_vendors():
        if vendor == "claude_code":
            continue
        assert f"{vendor}-hooks.json" in emitted, vendor


def test_no_fragment_carries_a_matcher(tmp_path: Path) -> None:
    """The reason this surface reaches six vendors where the write path reaches two."""
    emitted = _emit(tmp_path, *_policy(tmp_path))
    rendered = json.dumps({name: doc for name, doc in emitted.items() if name != GATE_FILE})
    assert "matcher" not in rendered


def test_each_fragment_is_registered_under_the_vendors_own_turn_end_spelling(tmp_path: Path) -> None:
    """`Stop` for most, `AfterAgent` for gemini and tabnine -- read upstream, not written here."""
    emitted = _emit(tmp_path, *_policy(tmp_path))
    for vendor in vendors.stop_vendors():
        if vendor == "claude_code":
            continue
        assert vendors.stop_event(vendor) in json.dumps(emitted[f"{vendor}-hooks.json"]), vendor


def test_the_command_points_at_this_surfaces_own_gate(tmp_path: Path) -> None:
    """Not the pre-tool one: the two are separate files and a crossed reference would rot silently."""
    emitted = _emit(tmp_path, *_policy(tmp_path))
    assert "/leaky/stop/gate.json" in json.dumps(emitted[STOP_FRAGMENT])


# --- and what it deliberately refuses to emit ----------------------------------------------------


def test_a_policy_that_did_not_ask_for_tool_use_gets_nothing(tmp_path: Path) -> None:
    policy, manifest = _policy(tmp_path, on=("commit",))
    assert _emit(tmp_path, policy, manifest) == {}


def test_a_guard_only_policy_gets_nothing(tmp_path: Path) -> None:
    """A guard script judges a command, and a finished turn has none to hand it."""
    policy, manifest = _policy(tmp_path, script=True)
    emitted = _emit(tmp_path, policy, manifest)
    assert emitted, "it still has a declarative gate, which is what this surface runs"
    assert not any("--guard" in json.dumps(doc) for doc in emitted.values())


def test_a_kind_a_write_cannot_answer_gets_nothing(tmp_path: Path) -> None:
    """`forbidden_ref` reads a branch name; the runner refuses it here, so emitting is noise."""
    policy, manifest = _policy(tmp_path, kind="forbidden_ref")
    assert _emit(tmp_path, policy, manifest) == {}


# --- what it is worth, which is deliberately nothing ---------------------------------------------


@pytest.mark.parametrize("agent", sorted(SURFACE_AGENTS))
def test_stop_alone_credits_no_agent(agent: str) -> None:
    """A backstop that fires after every tool call in the turn has run is not coverage."""
    assert coverage_level({Surface.STOP}, agent) == "none"


@pytest.mark.parametrize("agent", sorted(SURFACE_AGENTS))
def test_adding_stop_never_raises_a_grade(agent: str) -> None:
    """Whatever the policy already achieved, wiring a turn-end hook does not improve the word."""
    for base in ({Surface.AMBIENT_RULE}, {Surface.GIT_HOOK}, {Surface.AMBIENT_RULE, Surface.GIT_HOOK}):
        before = coverage_level(base, agent, ci_gate_installed=True)
        after = coverage_level(base | {Surface.STOP}, agent, ci_gate_installed=True)
        assert before == after, f"{agent}: {sorted(s.value for s in base)}"
