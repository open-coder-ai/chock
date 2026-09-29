"""`action: warn | ask | block`: what the runner does with a violation at each surface."""

from __future__ import annotations

import json
import subprocess
import textwrap
from pathlib import Path

import pytest
from conftest import init_repo

from chock.gate.runner import ACTION_ASK, ACTION_WARN, ALLOW_ENV, EXIT_ASK, EXIT_WARN, run

POLICY = "demo-policy"
BAD = "BAD = 1\n"
OK = "OK = 1\n"

SCRIPT_TEMPLATE = textwrap.dedent(
    """\
    import sys
    sys.stderr.write({words!r})
    sys.exit({code})
    """
)


def _gate(repo: Path, action: str, kind: str = "content_regex", params: dict | None = None) -> Path:
    """A compiled gate where `chock sync` leaves one, so the runner can name its policy."""
    gate = repo / ".chock" / "compiled" / POLICY / "git-hook" / "gate.json"
    gate.parent.mkdir(parents=True, exist_ok=True)
    spec = {
        "kind": kind,
        "on": ["commit", "push", "tool_use"],
        "action": action,
        "message": "no BAD",
        "params": params or {"content_pattern": "BAD"},
    }
    gate.write_text(json.dumps(spec), encoding="utf-8")
    return gate


def _script_gate(repo: Path, action: str, code: int, words: str = "script says so\n") -> Path:
    (repo / "impl").mkdir(exist_ok=True)
    (repo / "impl" / "s.py").write_text(SCRIPT_TEMPLATE.format(code=code, words=words), encoding="utf-8")
    return _gate(repo, action, "script", {"script": "impl/s.py"})


def _stage(repo: Path, text: str) -> None:
    (repo / "app.py").write_text(text, encoding="utf-8")
    subprocess.run(["git", "add", "app.py"], cwd=repo, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    return init_repo(tmp_path)


# --- block is unchanged, and the default ----------------------------------------------------------


@pytest.mark.parametrize("event", ["pre-commit", "pre-push"])
def test_block_refuses_at_git_events(repo: Path, event: str) -> None:
    _stage(repo, BAD)
    assert run(_gate(repo, "block"), event, "", repo) == 1


def test_a_gate_without_an_action_still_blocks(repo: Path) -> None:
    gate = _gate(repo, "block")
    spec = json.loads(gate.read_text(encoding="utf-8"))
    del spec["action"]
    gate.write_text(json.dumps(spec), encoding="utf-8")
    _stage(repo, BAD)
    assert run(gate, "pre-commit", None, repo) == 1


def test_an_unknown_action_cannot_judge(repo: Path, capsys: pytest.CaptureFixture) -> None:
    _stage(repo, BAD)
    assert run(_gate(repo, "verify"), "pre-commit", None, repo) == 2
    assert "unknown action 'verify'" in capsys.readouterr().err


# --- warn never blocks ----------------------------------------------------------------------------


@pytest.mark.parametrize("event", ["pre-commit", "pre-push"])
def test_warn_prints_the_reason_and_allows_at_git_events(repo: Path, event: str, capsys: pytest.CaptureFixture) -> None:
    _stage(repo, BAD)
    assert run(_gate(repo, "warn"), event, "", repo) == 0
    err = capsys.readouterr().err
    assert "no BAD" in err
    assert "warning" in err
    assert "app.py: content pattern" in err


def test_warn_at_ci_is_a_workflow_annotation(repo: Path, capsys: pytest.CaptureFixture) -> None:
    _stage(repo, OK)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=repo, check=True, capture_output=True)
    _stage(repo, BAD)
    subprocess.run(["git", "commit", "-qm", "bad"], cwd=repo, check=True, capture_output=True)
    assert run(_gate(repo, "warn"), "ci", None, repo, base="HEAD~1") == 0
    out = capsys.readouterr().out
    assert out.startswith(f"::warning title=chock {POLICY}::no BAD%0A")
    assert "\n" not in out.strip()


@pytest.mark.parametrize(("event", "code"), [("pre-tool-use", EXIT_WARN), ("stop", EXIT_WARN)])
def test_warn_in_the_agent_exits_with_the_warn_code(
    repo: Path, event: str, code: int, capsys: pytest.CaptureFixture
) -> None:
    assert run(_gate(repo, "warn"), event, None, repo, writes={"app.py": BAD}) == code
    assert "no BAD" in capsys.readouterr().err


def test_a_clean_change_is_silent_under_every_action(repo: Path, capsys: pytest.CaptureFixture) -> None:
    _stage(repo, OK)
    for action in ("block", "ask", "warn"):
        assert run(_gate(repo, action), "pre-commit", None, repo) == 0
    assert capsys.readouterr().err == ""


# --- ask needs a person ---------------------------------------------------------------------------


def test_ask_refuses_a_commit_and_names_the_override(repo: Path, capsys: pytest.CaptureFixture) -> None:
    _stage(repo, BAD)
    assert run(_gate(repo, "ask"), "pre-commit", None, repo) == 1
    err = capsys.readouterr().err
    assert f"{ALLOW_ENV}={POLICY}" in err
    assert "cannot prompt" in err


def test_ask_is_answered_by_a_person_naming_the_policy(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    _stage(repo, BAD)
    monkeypatch.setenv(ALLOW_ENV, f"other, {POLICY}")
    assert run(_gate(repo, "ask"), "pre-commit", None, repo) == 0
    assert "allowed by CHOCK_ALLOW" in capsys.readouterr().err


@pytest.mark.parametrize("value", ["other", "", "*", "demo"])
def test_ask_is_not_answered_by_a_different_policy_or_a_wildcard(
    repo: Path, monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    _stage(repo, BAD)
    monkeypatch.setenv(ALLOW_ENV, value)
    assert run(_gate(repo, "ask"), "pre-commit", None, repo) == 1


def test_ask_is_answered_at_push_too(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _stage(repo, BAD)
    gate = _gate(repo, "ask")
    assert run(gate, "pre-push", "", repo) == 1
    monkeypatch.setenv(ALLOW_ENV, POLICY)
    assert run(gate, "pre-push", "", repo) == 0


@pytest.mark.parametrize(
    "marker", [{"CLAUDECODE": "1"}, {"AI_AGENT": "claude-code_1_agent"}, {"CHOCK_AGENT_COMMIT": "1"}]
)
def test_an_agent_cannot_answer_an_ask(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture, marker: dict
) -> None:
    _stage(repo, BAD)
    monkeypatch.setenv(ALLOW_ENV, POLICY)
    for name, value in marker.items():
        monkeypatch.setenv(name, value)
    assert run(_gate(repo, "ask"), "pre-commit", None, repo) == 1
    err = capsys.readouterr().err
    assert "treated as an agent's" in err
    assert f"{ALLOW_ENV}={POLICY} CHOCK_AGENT_COMMIT=0" in err


def test_a_person_in_an_agent_terminal_answers_with_the_escape_hatch(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stage(repo, BAD)
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.setenv(ALLOW_ENV, POLICY)
    monkeypatch.setenv("CHOCK_AGENT_COMMIT", "0")
    assert run(_gate(repo, "ask"), "pre-commit", None, repo) == 0


def test_ask_does_not_override_a_block(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _stage(repo, BAD)
    monkeypatch.setenv(ALLOW_ENV, POLICY)
    assert run(_gate(repo, "block"), "pre-commit", None, repo) == 1


def test_ask_at_ci_is_a_warning(repo: Path, capsys: pytest.CaptureFixture) -> None:
    _stage(repo, OK)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=repo, check=True, capture_output=True)
    _stage(repo, BAD)
    subprocess.run(["git", "commit", "-qm", "bad"], cwd=repo, check=True, capture_output=True)
    assert run(_gate(repo, "ask"), "ci", None, repo, base="HEAD~1") == 0
    assert capsys.readouterr().out.startswith("::warning")


def test_ask_at_pre_tool_use_asks_and_at_stop_only_warns(repo: Path) -> None:
    gate = _gate(repo, "ask")
    assert run(gate, "pre-tool-use", None, repo, writes={"app.py": BAD}) == EXIT_ASK
    assert run(gate, "stop", None, repo, writes={"app.py": BAD}) == EXIT_WARN


# --- a script chooses its verdict, under the declared action -------------------------------------


@pytest.mark.parametrize(
    ("action", "code", "exit_code"), [("block", 4, 0), ("block", 3, 1), ("ask", 4, 0), ("warn", 3, 0)]
)
def test_a_script_verdict_is_capped_by_the_declared_action(repo: Path, action: str, code: int, exit_code: int) -> None:
    _stage(repo, OK)
    assert run(_script_gate(repo, action, code), "pre-commit", None, repo) == exit_code


def test_a_script_exit_zero_allows(repo: Path) -> None:
    _stage(repo, OK)
    assert run(_script_gate(repo, "block", 0), "pre-commit", None, repo) == 0


def test_a_script_warn_reaches_the_agent_as_a_warning(repo: Path, capsys: pytest.CaptureFixture) -> None:
    gate = _script_gate(repo, "block", 4, "careful here\n")
    assert run(gate, "pre-tool-use", None, repo, writes={"app.py": OK}) == EXIT_WARN
    assert "careful here" in capsys.readouterr().err


def test_a_script_ask_reaches_the_agent_as_an_ask(repo: Path) -> None:
    assert run(_script_gate(repo, "block", 3), "pre-tool-use", None, repo, writes={"app.py": OK}) == EXIT_ASK


def test_a_script_ask_at_commit_needs_the_override(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _stage(repo, OK)
    gate = _script_gate(repo, "block", 3)
    assert run(gate, "pre-commit", None, repo) == 1
    monkeypatch.setenv(ALLOW_ENV, POLICY)
    assert run(gate, "pre-commit", None, repo) == 0


@pytest.mark.parametrize(("action", "exit_code"), [("block", 1), ("ask", 1), ("warn", 0)])
def test_a_script_that_crashes_takes_the_declared_action(
    repo: Path, action: str, exit_code: int, capsys: pytest.CaptureFixture
) -> None:
    _stage(repo, OK)
    gate = _script_gate(repo, action, 1, "Traceback (most recent call last):\n  boom\n")
    assert run(gate, "pre-commit", None, repo) == exit_code
    assert "crashed" in capsys.readouterr().err


def test_a_script_that_exits_one_without_a_reason_is_a_crash_not_a_verdict(
    repo: Path, capsys: pytest.CaptureFixture
) -> None:
    _stage(repo, OK)
    assert run(_script_gate(repo, "warn", 1, ""), "pre-commit", None, repo) == 0
    assert "crashed" in capsys.readouterr().err


def test_a_script_reason_on_exit_one_is_a_deliberate_block(repo: Path, capsys: pytest.CaptureFixture) -> None:
    _stage(repo, OK)
    assert run(_script_gate(repo, "block", 1, "no way\n"), "pre-commit", None, repo) == 1
    assert "no way" in capsys.readouterr().err


@pytest.mark.parametrize(("action", "exit_code"), [("block", 1), ("warn", 0)])
def test_an_unknown_script_exit_takes_the_declared_action(repo: Path, action: str, exit_code: int) -> None:
    _stage(repo, OK)
    assert run(_script_gate(repo, action, 7), "pre-commit", None, repo) == exit_code


# --- the gate log says what happened --------------------------------------------------------------


def _records(repo: Path) -> list[dict]:
    log = repo / ".chock" / "log" / "gate-events.jsonl"
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]


def test_the_log_records_warn_ask_and_the_override(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CHOCK_GATE_LOG")
    _stage(repo, BAD)
    run(_gate(repo, "warn"), "pre-commit", None, repo)
    run(_gate(repo, "ask"), "pre-commit", None, repo)
    monkeypatch.setenv(ALLOW_ENV, POLICY)
    run(_gate(repo, "ask"), "pre-commit", None, repo)
    records = _records(repo)
    assert [r["verdict"] for r in records] == [ACTION_WARN, ACTION_ASK, "allow"]
    assert [r.get("override") for r in records] == [None, None, ALLOW_ENV]
