"""Nothing the judged actor can edit lowers the rollout level: an agent reads HEAD's, a pull request its base's."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from conftest import init_repo
from test_rollout import _config, _gate, _git, _judge, _log, _uncommitted

from chock.gate.runner import GATE_LOG_ENV, ROLLOUT_ENV, judge
from chock.lifecycle import status_main


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    init_repo(tmp_path)
    (tmp_path / "base.txt").write_text("ok\n", encoding="utf-8")
    _git(tmp_path, "add", "base.txt")
    _git(tmp_path, "commit", "-qm", "base")
    return tmp_path


# --- an agent is held to the committed level ---------------------------------------------------------


def test_an_agent_cannot_lower_its_own_level_by_editing_the_config(repo: Path) -> None:
    _uncommitted(repo, "rollout: observe\n")
    assert _judge(repo, "pre-tool-use") == (1, "block")


def test_a_person_can_trial_an_uncommitted_level_on_their_own_commit(repo: Path) -> None:
    _uncommitted(repo, "rollout: observe\n")
    assert _judge(repo, "pre-commit") == (0, "warn")


def test_an_agents_commit_is_held_to_the_committed_level(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLAUDECODE", "1")
    _uncommitted(repo, "rollout: observe\n")
    assert _judge(repo, "pre-commit") == (1, "block")


def test_an_uncommitted_raise_still_counts_for_an_agent(repo: Path) -> None:
    """HEAD at observe, the working tree back at enforce: the stricter of the two holds."""
    _config(repo, "rollout: observe\n")
    _uncommitted(repo, "rollout: enforce\n")
    assert _judge(repo, "pre-tool-use") == (1, "block")


def test_a_committed_level_applies_to_an_agent(repo: Path) -> None:
    _config(repo, "rollout: observe\n")
    assert _judge(repo, "pre-tool-use") == (4, "warn")


# --- a pull request is held to its base's level ------------------------------------------------------


def test_a_pull_request_cannot_lower_the_gates_that_judge_it(repo: Path) -> None:
    gate = _gate(repo)
    _config(repo, "rollout: observe\n")
    (repo / "App.java").write_text("BAD = 1\n", encoding="utf-8")
    _git(repo, "add", "App.java")
    _git(repo, "commit", "-qm", "bad")
    assert judge(gate, "ci", None, repo, base="HEAD~2") == (1, "block")


def test_a_level_the_base_already_had_applies_at_ci(repo: Path) -> None:
    _config(repo, "rollout: observe\n")
    assert _judge(repo, "ci") == (0, "warn")


def test_the_override_is_never_read_at_ci(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ROLLOUT_ENV, "observe")
    assert _judge(repo, "ci") == (1, "block")


# --- the evidence and the config file ----------------------------------------------------------------


def test_what_observe_let_through_is_logged_even_with_the_log_off(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(GATE_LOG_ENV, "0")
    _config(repo, "rollout: observe\n")
    _judge(repo, "pre-tool-use")
    (record,) = _log(repo)
    assert record["would_block"] is True


def test_the_log_switch_still_silences_ordinary_records(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(GATE_LOG_ENV, "0")
    _judge(repo, "pre-tool-use")
    assert not (repo / ".chock" / "log" / "gate-events.jsonl").exists()


@pytest.mark.skipif(os.name == "nt", reason="symlinks need privileges on Windows")
def test_a_symlinked_config_is_enforce(repo: Path, tmp_path_factory: pytest.TempPathFactory) -> None:
    target = tmp_path_factory.mktemp("elsewhere") / "config.yaml"
    target.write_text("rollout: observe\n", encoding="utf-8")
    (repo / ".chock").mkdir(exist_ok=True)
    (repo / ".chock" / "config.yaml").symlink_to(target)
    assert _judge(repo, "pre-commit") == (1, "block")


# --- status names where the level came from ----------------------------------------------------------


def test_status_names_the_config_as_the_source(repo: Path, capsys: pytest.CaptureFixture) -> None:
    _config(repo, "rollout: observe\n")
    status_main(["--repo", str(repo), "--only", "log"])
    first = capsys.readouterr().out.splitlines()[0]
    assert first.startswith("ROLLOUT: observe, from `rollout:` in .chock/config.yaml")
    assert "command guards, tool_call gates and the MCP gateway still block" in first


def test_status_names_a_persons_override_as_the_source(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    monkeypatch.setenv(ROLLOUT_ENV, "ask")
    status_main(["--repo", str(repo), "--only", "log"])
    first = capsys.readouterr().out.splitlines()[0]
    assert first.startswith(f"ROLLOUT: ask, from {ROLLOUT_ENV}=ask in this shell")
    assert "an ask does not fail CI" in first
