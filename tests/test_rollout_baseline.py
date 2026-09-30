"""A rollout downgrade is a weakening, and `chock status` leads with a level below enforce."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
import yaml
from conftest import init_repo

from chock.gate.runner import ROLLOUT_ENV
from chock.lifecycle import status_main
from chock.validation.checks_baseline import Weakening, weakenings
from chock.validation.checks_baseline import main as baseline_main


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def _config(repo: Path, text: str) -> None:
    (repo / ".chock").mkdir(exist_ok=True)
    (repo / ".chock" / "config.yaml").write_text(text, encoding="utf-8")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    return init_repo(tmp_path)


# --- a downgrade is a weakening the baseline check refuses ----------------------------------------------


def _with(level: str | None) -> dict:
    return {} if level is None else {"rollout": level}


@pytest.mark.parametrize(
    ("was", "now"),
    [("enforce", "ask"), ("enforce", "observe"), ("ask", "observe"), (None, "observe"), (None, "ask")],
)
def test_lowering_the_level_is_a_weakening(was: str | None, now: str) -> None:
    found = weakenings(_with(was), _with(now))
    assert [w.policy_id for w in found] == ["rollout"]
    assert found[0].now == now


@pytest.mark.parametrize(
    ("was", "now"),
    [
        ("observe", "ask"),
        ("observe", "enforce"),
        ("ask", "enforce"),
        ("observe", "observe"),
        ("ask", "ask"),
        (None, None),
        (None, "enforce"),
        ("enforce", None),
        ("observe", "bogus"),
        ("enforce", "bogus"),
    ],
)
def test_raising_or_keeping_the_level_is_not(was: str | None, now: str | None) -> None:
    assert weakenings(_with(was), _with(now)) == []


def test_a_base_with_no_config_was_enforce() -> None:
    assert weakenings(None, _with("observe")) == [Weakening("rollout", "enforce", "observe")]
    assert weakenings(None, None) == []


def test_a_head_that_deletes_the_config_is_not_a_downgrade() -> None:
    """No config means enforce, so removing one that named observe only tightens."""
    assert weakenings(_with("observe"), None) == []


def _base_repo(tmp_path: Path, config: dict) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@e")
    _git(repo, "config", "user.name", "t")
    _config(repo, yaml.safe_dump(config))
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")
    return repo


def test_a_branch_that_lowers_the_level_fails_against_main(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    repo = _base_repo(tmp_path, {"rollout": "enforce"})
    _config(repo, yaml.safe_dump({"rollout": "observe"}))
    assert baseline_main(["--repo", str(repo), "--base", "main"]) == 1
    assert "rollout: enforce -> observe" in capsys.readouterr().out


def test_a_branch_that_raises_the_level_passes(tmp_path: Path) -> None:
    repo = _base_repo(tmp_path, {"rollout": "observe"})
    _config(repo, yaml.safe_dump({"rollout": "enforce"}))
    assert baseline_main(["--repo", str(repo), "--base", "main"]) == 0


# --- status says so first ------------------------------------------------------------------------------


@pytest.mark.parametrize("level", ["observe", "ask"])
def test_status_leads_with_a_level_below_enforce(repo: Path, level: str, capsys: pytest.CaptureFixture) -> None:
    _config(repo, f"rollout: {level}\n")
    assert status_main(["--repo", str(repo), "--only", "log"]) == 0
    assert capsys.readouterr().out.splitlines()[0].startswith(f"ROLLOUT: {level}")


@pytest.mark.parametrize("config", ["rollout: enforce\n", "", "rollout: nonsense\n"])
def test_status_is_silent_about_enforce(repo: Path, config: str, capsys: pytest.CaptureFixture) -> None:
    _config(repo, config)
    assert status_main(["--repo", str(repo), "--only", "log"]) == 0
    assert "ROLLOUT" not in capsys.readouterr().out


def test_status_for_an_agent_ignores_the_override(repo: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.setenv(ROLLOUT_ENV, "observe")
    status_main(["--repo", str(repo), "--only", "log"])
    assert "ROLLOUT" not in capsys.readouterr().out


def test_the_log_summary_counts_would_block() -> None:
    from chock.gatelog import render_text, summarize

    events = [
        {"policy_id": "p", "surface": "s", "verdict": "warn", "would_block": True},
        {"policy_id": "p", "surface": "s", "verdict": "warn"},
    ]
    (entry,) = summarize(events)
    assert (entry["warn"], entry["would_block"]) == (2, 1)
    assert "would_block" in render_text([entry], [])
    assert "would_block" not in render_text(summarize(events[1:]), [])
