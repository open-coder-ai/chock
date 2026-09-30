"""`rollout: observe | ask | enforce`: how far gates may escalate, and who may move it."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from conftest import init_repo

from chock.gate import runner
from chock.gate.runner import GATE_LOG_ENV, ROLLOUT_ENV, judge, rollout_level, script_verdict

POLICY = "demo-policy"
LEVELS = ("observe", "ask", "enforce")
#: (git commit, tool use, ci) -> (exit code, verdict) for a block gate that finds a violation.
EXPECTED = {
    "enforce": {"pre-commit": (1, "block"), "pre-tool-use": (1, "block"), "ci": (1, "block")},
    "ask": {"pre-commit": (1, "ask"), "pre-tool-use": (3, "ask"), "ci": (0, "ask")},
    "observe": {"pre-commit": (0, "warn"), "pre-tool-use": (4, "warn"), "ci": (0, "warn")},
}


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def _config(repo: Path, text: str) -> None:
    (repo / ".chock").mkdir(exist_ok=True)
    (repo / ".chock" / "config.yaml").write_text(text, encoding="utf-8")


def _gate(repo: Path, action: str = "block") -> Path:
    gate = repo / ".chock" / "compiled" / POLICY / "git-hook" / "gate.json"
    gate.parent.mkdir(parents=True, exist_ok=True)
    spec = {
        "kind": "content_regex",
        "on": ["commit", "push", "tool_use"],
        "action": action,
        "message": "no BAD",
        "params": {"content_pattern": "BAD"},
    }
    gate.write_text(json.dumps(spec), encoding="utf-8")
    return gate


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    init_repo(tmp_path)
    (tmp_path / "base.txt").write_text("ok\n", encoding="utf-8")
    _git(tmp_path, "add", "base.txt")
    _git(tmp_path, "commit", "-qm", "base")
    return tmp_path


def _judge(repo: Path, event: str, action: str = "block") -> tuple[int, str]:
    """Judge a violating change at `event`: staged for git, committed for ci, a pending write for tool use."""
    gate = _gate(repo, action)
    if event == "pre-tool-use":
        return judge(gate, event, None, repo, writes={"App.java": "BAD = 1\n"})
    (repo / "App.java").write_text("BAD = 1\n", encoding="utf-8")
    _git(repo, "add", "App.java")
    if event == "ci":
        _git(repo, "commit", "-qm", "bad")
        return judge(gate, event, None, repo, base="HEAD~1")
    return judge(gate, event, "", repo)


def _log(repo: Path) -> list[dict]:
    path = repo / ".chock" / "log" / "gate-events.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


# --- all three levels at all three events -----------------------------------------------------------


@pytest.mark.parametrize("event", ["pre-commit", "pre-tool-use", "ci"])
@pytest.mark.parametrize("level", LEVELS)
def test_each_level_caps_a_block_gate_at_each_event(repo: Path, level: str, event: str) -> None:
    _config(repo, f"rollout: {level}\n")
    assert _judge(repo, event) == EXPECTED[level][event]


@pytest.mark.parametrize("event", ["pre-commit", "pre-tool-use", "ci"])
def test_no_rollout_key_is_enforce(repo: Path, event: str) -> None:
    _config(repo, "policies:\n  disabled: []\n")
    assert _judge(repo, event) == EXPECTED["enforce"][event]


def test_no_config_file_is_enforce(repo: Path) -> None:
    assert _judge(repo, "pre-tool-use") == (1, "block")


@pytest.mark.parametrize("level", LEVELS)
def test_a_clean_change_is_allowed_at_every_level(repo: Path, level: str) -> None:
    _config(repo, f"rollout: {level}\n")
    (repo / "Fine.java").write_text("OK = 1\n", encoding="utf-8")
    assert judge(_gate(repo), "pre-tool-use", None, repo, writes={"Fine.java": "OK = 1\n"}) == (0, "allow")


@pytest.mark.parametrize(
    ("declared", "level", "verdict"),
    [("warn", "enforce", "warn"), ("warn", "ask", "warn"), ("ask", "observe", "warn"), ("ask", "ask", "ask")],
)
def test_the_rollout_never_raises_the_declared_action(repo: Path, declared: str, level: str, verdict: str) -> None:
    _config(repo, f"rollout: {level}\n")
    assert _judge(repo, "pre-tool-use", declared)[1] == verdict


# --- a bad value fails closed ------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "rollout: Observe\n",
        "rollout: off\n",
        "rollout:\n",
        "rollout: observe extra\n",
        "rollout: [observe]\n",
        "rollout: observe\nrollout: observe\n",
        "chock:\n  rollout: observe\n",
        "  rollout: observe\n",
        "# rollout: observe\n",
    ],
)
def test_an_unknown_or_ambiguous_value_is_enforce(repo: Path, text: str) -> None:
    _config(repo, text)
    assert _judge(repo, "pre-tool-use") == (1, "block")


def test_an_unreadable_config_is_enforce(repo: Path) -> None:
    (repo / ".chock").mkdir(exist_ok=True)
    (repo / ".chock" / "config.yaml").write_bytes(b"rollout: observe\n\xff\xfe")
    assert _judge(repo, "pre-tool-use") == (1, "block")


@pytest.mark.parametrize("raw", ["observe", " ask ", "'observe'", '"enforce"'])
def test_rollout_level_reads_the_three_names(raw: str) -> None:
    assert rollout_level(raw) == raw.strip().strip("'\"")


@pytest.mark.parametrize("raw", [None, 5, True, ["observe"], "", "OBSERVE", "warn"])
def test_rollout_level_anything_else_is_enforce(raw: object) -> None:
    assert rollout_level(raw) == "enforce"


# --- the env override: a person's own git command only -----------------------------------------------


def test_a_person_may_set_the_level_for_their_own_commit(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ROLLOUT_ENV, "observe")
    assert _judge(repo, "pre-commit") == (0, "warn")


@pytest.mark.parametrize("env", [{"CLAUDECODE": "1"}, {"AI_AGENT": "claude-code_2_agent"}, {"CHOCK_AGENT_COMMIT": "1"}])
def test_an_agents_commit_ignores_the_override(repo: Path, monkeypatch: pytest.MonkeyPatch, env: dict) -> None:
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv(ROLLOUT_ENV, "observe")
    assert _judge(repo, "pre-commit") == (1, "block")


@pytest.mark.parametrize("event", ["pre-tool-use", "ci"])
def test_the_override_is_never_honoured_at_tool_use_or_ci(
    repo: Path, monkeypatch: pytest.MonkeyPatch, event: str
) -> None:
    """Even with no agent marker set: a tool call's actor is the agent, and ci has no person's shell."""
    monkeypatch.setenv(ROLLOUT_ENV, "observe")
    assert _judge(repo, event) == (1, "block")


def test_the_override_cannot_go_past_what_the_config_names_for_an_agent(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _config(repo, "rollout: ask\n")
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.setenv(ROLLOUT_ENV, "observe")
    assert _judge(repo, "pre-tool-use") == (3, "ask")


@pytest.mark.parametrize("value", ["", "warn", "Observe", "0"])
def test_an_unknown_override_falls_back_to_the_config(repo: Path, monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    _config(repo, "rollout: ask\n")
    monkeypatch.setenv(ROLLOUT_ENV, value)
    assert _judge(repo, "pre-commit") == (1, "ask")


# --- the evidence ------------------------------------------------------------------------------------


def test_observe_logs_what_enforce_would_have_blocked(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    monkeypatch.delenv(GATE_LOG_ENV, raising=False)
    _config(repo, "rollout: observe\n")
    assert _judge(repo, "pre-tool-use") == (4, "warn")
    (record,) = _log(repo)
    assert record["verdict"] == "warn"
    assert record["would_block"] is True
    assert record["would_action"] == "block"
    assert record["rollout"] == "observe"
    assert "enforce would have stopped (block)" in capsys.readouterr().err


def test_an_ask_held_by_observe_is_recorded_as_not_a_block(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(GATE_LOG_ENV, raising=False)
    _config(repo, "rollout: observe\n")
    _judge(repo, "pre-tool-use", "ask")
    (record,) = _log(repo)
    assert (record["would_action"], record["would_block"]) == ("ask", False)


def test_enforce_writes_no_would_block_fields(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(GATE_LOG_ENV, raising=False)
    _judge(repo, "pre-tool-use")
    (record,) = _log(repo)
    assert record["verdict"] == "block"
    assert not {"would_block", "would_action", "rollout"} & record.keys()


def test_a_gate_the_level_did_not_change_records_nothing_extra(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(GATE_LOG_ENV, raising=False)
    _config(repo, "rollout: observe\n")
    _judge(repo, "pre-tool-use", "warn")
    assert "would_block" not in _log(repo)[0]


# --- script-backed git hooks -------------------------------------------------------------------------


def test_observe_lets_a_script_hooks_ask_through(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(GATE_LOG_ENV, raising=False)
    _config(repo, "rollout: observe\n")
    assert script_verdict(POLICY, "pre-commit", runner.EXIT_ASK, repo) == 0
    assert _log(repo)[0]["would_action"] == "ask"


@pytest.mark.parametrize("config", ["rollout: ask\n", "rollout: enforce\n", ""])
def test_a_script_hooks_ask_still_refuses_otherwise(repo: Path, config: str) -> None:
    _config(repo, config)
    assert script_verdict(POLICY, "pre-commit", runner.EXIT_ASK, repo) == 1


def test_a_script_hooks_ask_refuses_under_observe_for_an_agent(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Only the config lowers the level for an agent; the person-only env never reaches it."""
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.setenv(ROLLOUT_ENV, "observe")
    assert script_verdict(POLICY, "pre-commit", runner.EXIT_ASK, repo) == 1
