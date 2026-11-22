"""The `prompt_submit` event: a gate judges the prompt a person submits, only where agentseam says the client can refuse one."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from decision_log_support import settings
from prompt_submit_support import (
    BLOCKING,
    DETECT_ONLY,
    GATE,
    MESSAGE,
    NOT_WIRED,
    RECORDED,
    RECORDED_PROMPT,
    _fire,
    _fire_logging,
    _fragments,
    prompt_gate,
)
from tool_call_support import POLICY_ID, fire, make_repo

from chock import vendors
from chock.compile.levels import PROMPT_SUBMIT_TODAY
from chock.compile.surfaces import SURFACE_AGENTS, Surface
from chock.hooks.in_agent_install import WIRED_VENDORS, install_hooks, installed_policy_ids
from chock.hooks.runtime_vendor import vendor_runtime
from chock.hooks.sync_notes import PROMPT_SUBMIT_NO_HOOK, PROMPT_SUBMIT_UNTESTED, prompt_submit_lines
from chock.resources import package_data_dir

# --- which agents get a hook ----------------------------------------------------------------------


def test_only_agents_agentseam_says_can_block_a_prompt_get_a_hook() -> None:
    assert set(vendors.prompt_submit_vendors()) == BLOCKING
    assert (DETECT_ONLY | NOT_WIRED).isdisjoint(vendors.prompt_submit_vendors())
    assert {CHOCK for CHOCK, v in vendors.CHOCK_AGENT.items() if v in BLOCKING} == set(PROMPT_SUBMIT_TODAY)
    assert all(Surface.PROMPT_SUBMIT in SURFACE_AGENTS[a] for a in PROMPT_SUBMIT_TODAY)


def test_a_prompt_policy_emits_fragments_only_for_those_agents(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, prompt_gate())
    names = _fragments(repo)
    assert names == {"prompt-submit-gate.json", "prompt-submit.json"} | {
        f"{v}-hooks.json" for v in BLOCKING - {"claude_code"}
    }
    wire = {v: vendors.prompt_submit_event(v) for v in BLOCKING}
    assert wire["claude_code"] == "UserPromptSubmit" and wire["cursor"] == "beforeSubmitPrompt"


@pytest.mark.parametrize("vendor", sorted(BLOCKING - {"claude_code", "cursor"}))
def test_the_entry_comes_from_agentseam_not_a_hand_written_key(tmp_path: Path, vendor: str) -> None:
    repo = make_repo(tmp_path, prompt_gate())
    doc = json.loads((repo / ".chock/compiled" / POLICY_ID / "prompt-submit" / f"{vendor}-hooks.json").read_text())
    assert vendors.prompt_submit_event(vendor) in json.dumps(doc)
    assert "--prompt-submit" in json.dumps(doc)


def test_a_gate_the_agent_cannot_judge_emits_nothing(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, {"kind": "forbidden_ref", "on": ["prompt_submit"], "params": {"refs": ["x"]}})
    assert not _fragments(repo)


def test_installed_only_where_a_fragment_exists(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, prompt_gate())
    for vendor in WIRED_VENDORS:
        install_hooks(repo, vendor)
    assert {v for v in WIRED_VENDORS if POLICY_ID in installed_policy_ids(repo, v)} == BLOCKING
    claude = json.loads((repo / ".claude" / "settings.json").read_text())["hooks"]
    assert "--prompt-submit" in json.dumps(claude["UserPromptSubmit"])
    cursor = json.loads((repo / ".cursor" / "hooks.json").read_text())["hooks"]
    assert cursor["beforeSubmitPrompt"][0]["failClosed"] is True


def test_a_policy_gating_prompt_submit_and_tool_use_is_wired_at_both_events(tmp_path: Path) -> None:
    gate = {"kind": "content_regex", "on": ["tool_use", "prompt_submit"], "params": {"content_pattern": "aws key"}}
    repo = make_repo(tmp_path, {"action": "block", "message": MESSAGE, **gate})
    install_hooks(repo, "claude_code")
    events = json.loads((repo / ".claude" / "settings.json").read_text())["hooks"]
    assert {"PreToolUse", "UserPromptSubmit"} <= set(events)
    assert POLICY_ID in installed_policy_ids(repo, "claude_code")
    compiled = repo / ".chock/compiled" / POLICY_ID
    assert (compiled / "pre-tool-use").is_dir() and (compiled / "prompt-submit").is_dir()


# --- the label ------------------------------------------------------------------------------------


@pytest.mark.parametrize("vendor", sorted(BLOCKING))
def test_a_blocking_agent_is_labelled_with_agentseams_grade_and_untested(tmp_path: Path, vendor: str) -> None:
    repo = make_repo(tmp_path, prompt_gate())
    lines = prompt_submit_lines(vendor, repo)
    assert lines[0].startswith("prompt-submit: ") and "agentseam basis" in lines[0]
    assert lines[-1] == PROMPT_SUBMIT_UNTESTED


@pytest.mark.parametrize("vendor", sorted(DETECT_ONLY))
def test_a_detect_only_agent_is_told_it_got_no_hook(tmp_path: Path, vendor: str) -> None:
    repo = make_repo(tmp_path, prompt_gate())
    assert prompt_submit_lines(vendor, repo) == [PROMPT_SUBMIT_NO_HOOK]


def test_a_repo_with_no_prompt_gate_prints_no_prompt_line(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, {"kind": "content_regex", "on": ["commit"], "params": {"content_pattern": "x"}})
    assert prompt_submit_lines("claude_code", repo) == []


def test_coverage_credits_prompt_submit_only_to_agents_that_can_refuse(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, prompt_gate())
    for vendor in WIRED_VENDORS:
        install_hooks(repo, vendor)
    from chock.compile.compiler import compile_policy

    policy = repo / ".agents" / "policies" / POLICY_ID
    cells = compile_policy(policy, output_root=repo / ".chock" / "compiled", repo_root=repo).coverage[POLICY_ID]
    assert cells["claude"]["level"] == "best-effort" and cells["claude"]["witnessed"] is False
    assert cells["cursor"]["level"] == "enforceable" and cells["cursor"]["witnessed"] is False
    assert cells["goose"]["level"] != "best-effort" and cells["grok"]["level"] != "best-effort"
    assert cells["copilot"]["level"] not in {"best-effort", "enforceable"}


# --- the installed hook refuses, on each agent's recorded payload ---------------------------------


@pytest.mark.parametrize("vendor", sorted(BLOCKING))
def test_each_blocking_agent_refuses_its_recorded_payload_in_its_own_dialect(tmp_path: Path, vendor: str) -> None:
    repo = make_repo(tmp_path, prompt_gate())
    proc = _fire(repo, vendor)
    deny = RECORDED["deny"][vendor]
    assert proc.returncode == deny["exit"], proc.stderr
    assert proc.stdout.strip() == deny["stdout"].replace("policy", MESSAGE)
    assert RECORDED_PROMPT not in proc.stdout + proc.stderr, "the refusal never echoes the prompt"
    assert "aws key" not in proc.stdout + proc.stderr


@pytest.mark.parametrize("vendor", sorted(BLOCKING))
def test_a_clean_prompt_is_not_refused(tmp_path: Path, vendor: str) -> None:
    repo = make_repo(tmp_path, prompt_gate())
    proc = _fire(repo, vendor, prompt="add a retry to the uploader")
    assert proc.returncode == 0, proc.stderr
    assert MESSAGE not in proc.stdout + proc.stderr


def test_an_ask_gate_degrades_to_a_refusal_where_the_client_cannot_prompt(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, prompt_gate(action="ask"))
    proc = _fire(repo, "claude_code")
    assert json.loads(proc.stdout)["decision"] == "block"
    assert MESSAGE in json.loads(proc.stdout)["reason"]


def test_a_warn_gate_never_refuses(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, prompt_gate(action="warn"))
    assert '"block"' not in _fire(repo, "claude_code").stdout


def test_a_client_that_sends_no_prompt_is_refused_not_allowed(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, prompt_gate())
    vendor_runtime(repo, "claude_code")
    payload = {"hook_event_name": "UserPromptSubmit", "session_id": "s", "cwd": str(repo)}
    proc = fire(repo, ["--prompt-submit", GATE], payload)
    assert json.loads(proc.stdout)["decision"] == "block"


# --- the log --------------------------------------------------------------------------------------


@pytest.mark.parametrize("vendor", sorted(BLOCKING))
def test_the_decision_log_holds_the_policy_and_verdict_never_the_prompt(tmp_path: Path, vendor: str) -> None:
    repo = make_repo(tmp_path, prompt_gate())
    settings(repo, level="debug")
    lines = _fire_logging(repo, vendor)
    text = json.dumps(lines)
    record = lines[-1]
    assert (record["policy_id"], record["verdict"], record["surface"]) == (POLICY_ID, "block", "prompt-submit")
    assert "aws key" not in text and RECORDED_PROMPT not in text
    for key in ("aws", "deploy later"):
        assert key not in text


def test_the_log_stays_clean_of_the_prompt_for_an_allowed_one_too(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, prompt_gate())
    settings(repo, level="debug")
    lines = _fire_logging(repo, "claude_code", prompt="secret-marker-9137 refactor")
    assert lines and lines[-1]["verdict"] == "allow"
    assert "secret-marker-9137" not in json.dumps(lines)


# --- validation -----------------------------------------------------------------------------------


def _problems(gate: dict[str, Any], *, tool_use_allowed: bool = True) -> list[str]:
    from chock.validation.checks_gate_shape import _validate_gate
    from chock.validation.report import Report

    report = Report()
    _validate_gate(gate, "hook.gate", report, tool_use_allowed=tool_use_allowed)
    return [f.message for f in report.errors]


def test_the_two_kinds_that_read_text_validate() -> None:
    assert not _problems({"kind": "content_regex", "on": ["prompt_submit"], "params": {"content_pattern": "x"}})


def test_a_kind_that_cannot_read_a_prompt_is_refused() -> None:
    errors = _problems({"kind": "forbidden_ref", "on": ["prompt_submit"], "params": {"refs": ["x"]}})
    assert any("prompt_submit is judged by content_regex or script, not forbidden_ref" in e for e in errors)


def test_prompt_submit_is_a_hook_gate_event_not_a_gate_yaml_one() -> None:
    gate = {"kind": "content_regex", "on": ["prompt_submit"], "params": {"content_pattern": "x"}}
    assert any("only allowed in hook.gate" in e for e in _problems(gate, tool_use_allowed=False))


def test_the_manifest_schema_names_the_event() -> None:
    from chock.validation.loading import schema_validator

    schema = json.loads(
        package_data_dir("chock.validation", "schemas").joinpath("manifest.hook.json").read_text("utf-8")
    )
    assert "prompt_submit" in json.dumps(schema)
    assert schema_validator(schema) is not None
