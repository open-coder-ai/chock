"""A findings refusal leads with the finding; the agent gets the finding alone and never a waiver to write."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from conftest import stage
from findings_support import NAME, TOY, gate_spec, repo_with

from chock.gate.runner import GateResult, _reason, run

POLICY = "java-security: a construct one of its rules denies -- the finding names the rule and the fix."
WAIVER = "A path that must stay dynamic needs 'chock: allow java-path-traversal-request-data' on this line."
FINDING = f"src/Files.java:8: [deny: java-path-traversal-request-data CWE-22] Built from a request parameter. {WAIVER}"
FOUND = {"new_findings": 1, "baseline_findings": 0}
ASK_A_PERSON = "If this must stay, ask a person to review it; an agent cannot add the waiver."


def _findings(matches: list[str] | None = None) -> GateResult:
    return GateResult(allowed=False, matches=matches or [FINDING], detail=FOUND)


def _gate(repo: Path) -> Path:
    (repo / NAME).write_text(TOY, encoding="utf-8")
    gate = repo / "gate.json"
    gate.write_text(json.dumps({**gate_spec(), "message": POLICY}), encoding="utf-8")
    return gate


@pytest.fixture(autouse=True)
def _no_agent_marker(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("CLAUDECODE", "AI_AGENT", "CHOCK_AGENT_COMMIT"):
        monkeypatch.delenv(name, raising=False)


def test_a_tool_use_refusal_is_the_finding_then_one_pointer(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = repo_with(tmp_path, **{"app.py": "x = 1\n"})
    assert run(_gate(repo), "pre-tool-use", None, repo, writes={"app.py": "x = BAD\n"}) == 1
    lines = capsys.readouterr().err.splitlines()
    assert lines[0] == "app.py:1: bad x = BAD"
    assert len(lines) == 2
    assert "person customises" in lines[1]
    assert "java-security" not in "\n".join(lines)


def test_a_commit_refusal_is_the_findings_then_the_summary_then_the_policy(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = repo_with(tmp_path, **{"app.py": "x = 1\n"})
    stage(repo, "app.py", "x = BAD\n")
    assert run(_gate(repo), "pre-commit", None, repo) == 1
    lines = capsys.readouterr().err.splitlines()
    assert lines[0] == "app.py:1: bad x = BAD"
    assert lines[1] == "gate refused 1 new finding(s) (only lines this change adds are judged)."
    assert lines[2] == POLICY


def test_the_summary_names_the_policy() -> None:
    lines = _reason(_findings(), {"message": POLICY}, "commit", "java-security").splitlines()
    assert lines == [
        FINDING,
        "java-security refused 1 new finding(s) (only lines this change adds are judged).",
        POLICY,
    ]


def test_the_person_facing_commit_keeps_the_waiver_sentence() -> None:
    assert WAIVER in _reason(_findings(), {"message": POLICY}, "commit", "java-security")
    assert WAIVER in _reason(_findings(), {"message": POLICY}, "ci", "java-security")


@pytest.mark.parametrize("event", ["tool_use", "agent-commit"])
def test_an_agent_is_never_told_to_write_a_waiver(event: str) -> None:
    reason = _reason(_findings(), {"message": POLICY + " Add chock: allow <rule> to waive."}, event, "java-security")
    assert "chock: allow" not in reason
    assert ASK_A_PERSON in reason
    assert reason.startswith(FINDING.replace(WAIVER, ASK_A_PERSON))


def test_the_waiver_sentence_alone_is_replaced() -> None:
    reason = _reason(_findings(), {}, "tool_use", "java-security")
    assert "Built from a request parameter. " + ASK_A_PERSON in reason
    assert "[deny: java-path-traversal-request-data CWE-22]" in reason


def test_a_gate_without_findings_keeps_its_message_first() -> None:
    result = GateResult(allowed=False, message="no BAD", matches=["app.py: content pattern"])
    assert _reason(result, {}, "tool_use", "p") == "no BAD\n  - app.py: content pattern"
    assert _reason(result, {}, "commit", "p") == "no BAD\n  - app.py: content pattern"
