"""A rollout downgrade is a weakening, and `chock status` leads with a level below enforce."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
import yaml
from conftest import init_repo

from chock.gate.runner import ROLLOUT_ENV, rollout_from_text
from chock.lifecycle import status_main
from chock.validation.checks_baseline import Weakening, rollout_weakening
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


def _text(level: str | None) -> str | None:
    return None if level is None else f"rollout: {level}\n"


def _base_repo(tmp_path: Path, config: dict | str | None) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@e")
    _git(repo, "config", "user.name", "t")
    (repo / "README").write_text("r\n", encoding="utf-8")
    if config is not None:
        _config(repo, config if isinstance(config, str) else yaml.safe_dump(config))
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")
    return repo


def _lowered(tmp_path: Path, was: str | None, now: str | None) -> Weakening | None:
    repo = _base_repo(tmp_path, _text(was))
    path = repo / ".chock" / "config.yaml"
    if now is None:
        path.unlink(missing_ok=True)
    else:
        _config(repo, now)
    return rollout_weakening(repo, "main")


@pytest.mark.parametrize(
    ("was", "now"),
    [("enforce", "ask"), ("enforce", "observe"), ("ask", "observe"), (None, "observe"), (None, "ask")],
)
def test_lowering_the_level_is_a_weakening(tmp_path: Path, was: str | None, now: str) -> None:
    found = _lowered(tmp_path, was, _text(now))
    assert found is not None and (found.policy_id, found.now) == ("rollout", now)


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
        ("observe", None),
    ],
)
def test_raising_or_keeping_the_level_is_not(tmp_path: Path, was: str | None, now: str | None) -> None:
    assert _lowered(tmp_path, was, _text(now)) is None


#: Configs the runtime reads as observe though a YAML parser sees no `rollout` key: the baseline
#: check must read them as the runtime does, or a pull request lowers the level unseen.
DISGUISED = [
    'policies:\n  disabled: []\nnote: "a\nrollout: observe\nb"\n',
    "note: 'a\nrollout: observe\nb'\n",
    "rollout:observe\n",
    "[\nrollout: observe\n]\n",
]


@pytest.mark.parametrize("config", DISGUISED)
def test_a_downgrade_yaml_would_not_see_is_still_a_weakening(tmp_path: Path, config: str) -> None:
    assert rollout_from_text(config) == "observe", "the runtime reads these as observe"
    found = _lowered(tmp_path, None, config)
    assert found is not None and found.now == "observe"


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
