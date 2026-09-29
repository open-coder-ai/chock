"""Eval `expect` can pin `ask` and `warn`, at gate replays (git and agent events) and script events."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml
from conftest import baseline_policy

from chock.eval.execute import run_case
from chock.eval.model import Case
from chock.eval.suites import discover_policies

POLICY_ID = "keep-marker"
SECRET = 'KEY = "' + "AKIA" + "IOSFODNN7EXAMPLE" + '"\n'
CLEAN = "x = 1\n"
GIT_EVENTS = [{"files": {"app.py": SECRET}}, {"event": "push", "files": {"app.py": SECRET}, "push_refs": ["main"]}]
AGENT_EVENTS = [{"event": e, "writes": {"app.py": SECRET}} for e in ("tool_use", "pre-tool-use", "stop")]
_SCRIPT_GATE = "import sys\nprint('the script speaks', file=sys.stderr)\nraise SystemExit({code})\n"
_HOOK_SCRIPT = "import sys\nprint('the hook script speaks', file=sys.stderr)\nraise SystemExit({code})\n"


def _policy(repo: Path, action: str, files: dict[str, str] | None = None, gate: dict[str, Any] | None = None) -> None:
    """A rule policy whose gate declares `action`, plus whatever implementations the case needs."""
    policy = repo / ".agents" / "policies" / POLICY_ID
    (policy / "implementations").mkdir(parents=True)
    manifest = yaml.safe_load((baseline_policy("protect-commit-privacy") / "manifest.yaml").read_text(encoding="utf-8"))
    manifest["id"] = POLICY_ID
    manifest["enforcement"] = "block"
    manifest["hook"] = {}
    scripted = any(f.endswith("-pre-commit.py") for f in files or {})
    if not scripted:
        manifest["hook"]["gate"] = gate or {
            "kind": "content_regex",
            "on": ["commit", "push", "tool_use", "stop"],
            "action": action,
            "message": "a key",
            "params": {"content_pattern": "AKIA[0-9A-Z]{16}"},
        }
    if scripted:
        manifest["hook"]["script"] = {"on": ["commit"]}
    (policy / "manifest.yaml").write_text(yaml.safe_dump(manifest), encoding="utf-8")
    for name, text in (files or {}).items():
        (policy / "implementations" / name).write_text(text, encoding="utf-8")


def _run(repo: Path, execute: dict) -> tuple[str, str]:
    policy = discover_policies(repo, POLICY_ID)[0]
    result = run_case(Case("c1", "trigger", "p", "e", POLICY_ID, execute=execute), policy.dir, repo, policy.guards)
    return result.outcome, result.detail


def _outcomes(repo: Path, execute: dict, expects: tuple[str, ...]) -> dict[str, str]:
    return {expect: _run(repo, {**execute, "expect": expect})[0] for expect in expects}


ALL = ("allow", "block", "ask", "warn")


def _only(expected: str) -> dict[str, str]:
    return {e: "pass" if e == expected else "fail" for e in ALL}


@pytest.mark.parametrize("execute", AGENT_EVENTS, ids=lambda e: e["event"])
@pytest.mark.parametrize("action", ["block", "ask", "warn"])
def test_agent_event_gate_replays_its_declared_action(tmp_path: Path, execute: dict, action: str) -> None:
    _policy(tmp_path, action)
    expected = "warn" if action == "ask" and execute["event"] == "stop" else action  # a Stop ask is a warning
    assert _outcomes(tmp_path, execute, ALL) == _only(expected)


@pytest.mark.parametrize("event", ["tool_use", "stop"])
@pytest.mark.parametrize("action", ["block", "ask", "warn"])
def test_agent_event_clean_write_still_allows(tmp_path: Path, event: str, action: str) -> None:
    _policy(tmp_path, action)
    assert _outcomes(tmp_path, {"event": event, "writes": {"app.py": CLEAN}}, ALL) == _only("allow")


@pytest.mark.parametrize("execute", GIT_EVENTS, ids=["commit", "push"])
@pytest.mark.parametrize("action", ["block", "ask", "warn"])
def test_commit_and_push_gate_replays_its_declared_action(tmp_path: Path, execute: dict, action: str) -> None:
    _policy(tmp_path, action)
    assert _outcomes(tmp_path, execute, ALL) == _only(action)


def test_expect_block_against_an_ask_gate_fails_with_a_clear_message(tmp_path: Path) -> None:
    _policy(tmp_path, "ask")
    for execute in (GIT_EVENTS[0], AGENT_EVENTS[0]):
        outcome, detail = _run(tmp_path, {**execute, "expect": "block"})
        assert outcome == "fail"
        assert "expected block, observed ask; the gate asks rather than blocks" in detail


def test_expect_block_against_a_warn_gate_fails_with_a_clear_message(tmp_path: Path) -> None:
    _policy(tmp_path, "warn")
    outcome, detail = _run(tmp_path, {**AGENT_EVENTS[0], "expect": "block"})
    assert outcome == "fail" and "the gate warns rather than blocks" in detail


@pytest.mark.parametrize(("code", "verdict"), [(0, "allow"), (1, "block"), (3, "ask"), (4, "warn")])
def test_script_gate_verdict_by_exit_code_under_a_block_ceiling(tmp_path: Path, code: int, verdict: str) -> None:
    gate = {"kind": "script", "on": ["commit", "tool_use"], "action": "block", "params": {"script": "judge.py"}}
    _policy(tmp_path, "block", files={"judge.py": _SCRIPT_GATE.format(code=code)}, gate=gate)
    for execute in ({"files": {"app.py": SECRET}}, {"event": "tool_use", "writes": {"app.py": SECRET}}):
        assert _outcomes(tmp_path, execute, ALL) == _only(verdict)


def test_script_gate_is_capped_by_the_declared_action(tmp_path: Path) -> None:
    """`ask` + exit 1 asks; `warn` + exit 1 warns: the script never goes harsher than the gate."""
    for action in ("ask", "warn"):
        gate = {"kind": "script", "on": ["commit"], "action": action, "params": {"script": "judge.py"}}
        (tmp_path / action).mkdir()
        _policy(tmp_path / action, action, files={"judge.py": _SCRIPT_GATE.format(code=1)}, gate=gate)
        assert _outcomes(tmp_path / action, {"files": {"app.py": SECRET}}, ALL) == _only(action)


@pytest.mark.parametrize(("code", "verdict"), [(0, "allow"), (1, "block"), (3, "ask"), (4, "warn")])
def test_pre_commit_script_exit_codes_replay_as_their_verdicts(tmp_path: Path, code: int, verdict: str) -> None:
    _policy(tmp_path, "block", files={f"{POLICY_ID}-pre-commit.py": _HOOK_SCRIPT.format(code=code)})
    assert _outcomes(tmp_path, {"event": "pre-commit", "files": {"a.txt": "a\n"}}, ALL) == _only(verdict)


def test_a_script_exit_that_is_no_verdict_still_blocks(tmp_path: Path) -> None:
    _policy(tmp_path, "block", files={f"{POLICY_ID}-pre-commit.py": _HOOK_SCRIPT.format(code=5)})
    assert _outcomes(tmp_path, {"event": "pre-commit", "files": {"a.txt": "a\n"}}, ALL) == _only("block")
