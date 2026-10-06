"""`chock sync` records a committed toggle file only when it is byte-identical to the remote default branch."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from conftest import init_repo

from chock.guardrails import toggle
from chock.guardrails.reviewed import record_reviewed
from chock.lifecycle import sync_main

B, P = "chock-guardrails", "block-destructive-commands"
OFF = json.dumps({"version": 1, "bundles": {B: {P: "off"}}}) + "\n"


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _commit(repo: Path, text: str, message: str) -> None:
    (repo / ".chock").mkdir(exist_ok=True)
    (repo / toggle.FILENAME).write_text(text, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", message)


@pytest.fixture
def clone(tmp_path: Path) -> Path:
    """A teammate's fresh clone of a repository whose reviewed default branch switches one guardrail off."""
    (tmp_path / "upstream").mkdir()
    upstream = init_repo(tmp_path / "upstream")
    _git(upstream, "checkout", "-qb", "main")
    _commit(upstream, OFF, "reviewed toggle")
    _git(tmp_path, "clone", "-q", str(upstream), "clone")
    mine = tmp_path / "clone"
    _git(mine, "config", "user.email", "t@example.com")
    _git(mine, "config", "user.name", "t")
    return mine


def _off(repo: Path) -> bool:
    _path, _scope, toggles, _warning = toggle.load(repo)
    return toggle.state(toggles, B, P) == toggle.OFF


def test_a_fresh_clone_ignores_the_file_until_synced_then_the_reviewed_toggles_apply(clone: Path) -> None:
    assert not _off(clone), "no record yet: every guardrail stays on"
    sync_main(["--repo", str(clone), "--skip-hooks"])
    assert toggle.record_path(clone / toggle.FILENAME).is_file()
    assert _off(clone)


def test_a_local_commit_not_on_the_remote_is_never_recorded(clone: Path, capsys: pytest.CaptureFixture) -> None:
    _commit(clone, json.dumps({"version": 1, "bundles": {B: {P: "off", "scan-secrets": "off"}}}), "agent's commit")
    record_reviewed(clone)
    assert not toggle.record_path(clone / toggle.FILENAME).exists()
    assert "chock bundle status --adopt" in capsys.readouterr().out
    _path, _scope, toggles, warning = toggle.load(clone)
    assert toggles == {} and toggle.DRIFTED in (warning or "")


def test_no_remote_records_nothing(tmp_path: Path) -> None:
    (tmp_path / "solo").mkdir()
    repo = init_repo(tmp_path / "solo")
    _commit(repo, OFF, "local only")
    record_reviewed(repo)
    assert not toggle.record_path(repo / toggle.FILENAME).exists()
    assert not _off(repo)


def test_a_reviewed_file_hand_edited_afterwards_is_not_recorded(clone: Path) -> None:
    record_reviewed(clone)
    (clone / toggle.FILENAME).write_text(OFF.replace(P, "scan-secrets"), encoding="utf-8")
    record_reviewed(clone)
    assert not _off(clone) and toggle.drift(clone / toggle.FILENAME)
