"""The gate outcome log is per machine and grows on every commit; it must not be committed.

`chock init` never wrote an ignore rule for it, so an adopter who ran `git add -A` after
onboarding committed `.chock/log/gate-events.jsonl` and then saw it change on every commit.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from conftest import init_repo

from chock.scaffold.gitrules import GATE_LOG_IGNORE
from chock.scaffold.init import cmd_init
from chock.validation.checks_repo import check_gate_log_untracked
from chock.validation.report import Report


def _init(repo: Path) -> int:
    return cmd_init([str(repo), "--skip-hooks"])


def _ignored(repo: Path, rel: str) -> bool:
    return subprocess.run(["git", "check-ignore", "-q", rel], cwd=repo, check=False).returncode == 0


# --- init writes the rule ------------------------------------------------------------------------


def test_init_ignores_the_gate_log(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    assert _init(repo) == 0
    assert GATE_LOG_IGNORE in (repo / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert _ignored(repo, ".chock/log/gate-events.jsonl")


def test_the_rule_is_written_once(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    assert _init(repo) == 0
    assert _init(repo) == 0
    assert (repo / ".gitignore").read_text(encoding="utf-8").count(GATE_LOG_IGNORE) == 1


def test_an_adopters_own_gitignore_is_appended_to_not_replaced(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    (repo / ".gitignore").write_text("build/\n*.pyc", encoding="utf-8")  # no trailing newline on purpose
    assert _init(repo) == 0
    lines = (repo / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert lines[:2] == ["build/", "*.pyc"]
    assert GATE_LOG_IGNORE in lines


def test_a_rule_the_adopter_already_wrote_is_respected(tmp_path: Path) -> None:
    """`.chock/log` without the slash ignores the same directory; init must not add a second."""
    repo = init_repo(tmp_path)
    (repo / ".gitignore").write_text(".chock/log\n", encoding="utf-8")
    assert _init(repo) == 0
    lines = (repo / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert lines[0] == ".chock/log"
    assert GATE_LOG_IGNORE not in lines


# --- and validate says so when the log was committed anyway --------------------------------------


def _commit_log(repo: Path) -> None:
    log = repo / ".chock" / "log" / "gate-events.jsonl"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text('{"ts": "2026-01-01T00:00:00Z"}\n', encoding="utf-8")
    subprocess.run(["git", "add", "-f", ".chock/log/gate-events.jsonl"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "log"], cwd=repo, check=True)


def test_a_committed_gate_log_is_a_warning(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    _commit_log(repo)
    report = Report()
    check_gate_log_untracked(repo, report)
    assert [f.check for f in report.warnings] == ["gate_log_tracked"]
    assert "git rm --cached" in report.warnings[0].message


def test_an_ignored_gate_log_is_silent(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    assert _init(repo) == 0
    (repo / ".chock" / "log").mkdir(exist_ok=True)
    (repo / ".chock" / "log" / "gate-events.jsonl").write_text("{}\n", encoding="utf-8")
    report = Report()
    check_gate_log_untracked(repo, report)
    assert report.warnings == []


def test_outside_a_repository_is_silent(tmp_path: Path) -> None:
    report = Report()
    check_gate_log_untracked(tmp_path, report)
    assert report.warnings == []
