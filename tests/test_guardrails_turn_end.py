"""The turn-end check: a toggle file that differs from what `chock bundle` recorded refuses the Stop, in every format."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from bundle_fixtures import ALL_ROOTS, BUNDLE_ID, GUARD_ID
from conftest import run_hook_command
from guardrails_support import MERGED_CLIENTS, TOGGLE, build, outcomes

from chock.guardrails import cli, toggle
from chock.guardrails.plugin import WRAPPER


def _stop(client: str, repo: Path) -> dict:
    if client == "cursor":
        return {
            "conversation_id": "c",
            "generation_id": "g",
            "workspace_roots": [str(repo)],
            "cwd": str(repo),
            "hook_event_name": "stop",
            "status": "completed",
            "loop_count": 0,
        }
    return {"hook_event_name": "Stop", "stop_hook_active": False, "cwd": str(repo), "session_id": "s1"}


def _verdict(proc) -> str:
    out = proc.stdout.lower()
    if proc.returncode == 2 or '"block"' in out or '"deny"' in out or "followup_message" in out:
        return "refused" if "changed outside `chock bundle`" in (proc.stdout + proc.stderr) else f"other: {proc}"
    assert proc.returncode == 0, (proc.returncode, proc.stdout, proc.stderr)
    return "allowed"


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "home"
    path.mkdir()
    monkeypatch.setenv("HOME", str(path))
    monkeypatch.setenv("USERPROFILE", str(path))
    return path


def _at_turn_end(client: str, tmp_path: Path, home: Path):
    plugin, repo, commands = build(tmp_path, client)
    verify = [c for c in commands if f'{WRAPPER}" {toggle.VERIFY}' in c]
    assert len(verify) == 1, commands

    def judge() -> str:
        (proc,) = outcomes(verify, plugin, repo, _stop(client, repo), home)
        return _verdict(proc)

    return repo, judge


def _switch(repo: Path, monkeypatch: pytest.MonkeyPatch, *args: str) -> None:
    monkeypatch.chdir(repo)
    named = ["--bundle", BUNDLE_ID] if args[0] in toggle.STATES else []
    assert cli.main([*args, *named]) == 0


@pytest.mark.parametrize("client", MERGED_CLIENTS)
def test_the_persons_change_through_the_cli_passes_and_a_raw_write_is_refused(
    tmp_path: Path, home: Path, client: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, judge = _at_turn_end(client, tmp_path, home)
    assert judge() == "allowed", "no file, no record"
    _switch(repo, monkeypatch, "off", GUARD_ID)
    assert judge() == "allowed", "written by chock bundle"
    path = repo / TOGGLE
    # A write the best-effort shell guard missed: the file changes with no record of it.
    path.write_text(json.dumps({"version": 1, "bundles": {BUNDLE_ID: {GUARD_ID: "off", "demo-write-gate": "off"}}}))
    assert judge() == "refused"
    _switch(repo, monkeypatch, "status", "--adopt")
    assert judge() == "allowed", "a person reviewed and adopted it"


@pytest.mark.parametrize("client", MERGED_CLIENTS)
def test_deletion_and_a_missing_record_are_refused_until_adopted(
    tmp_path: Path, home: Path, client: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, judge = _at_turn_end(client, tmp_path, home)
    _switch(repo, monkeypatch, "off", GUARD_ID)
    (repo / TOGGLE).unlink()
    assert judge() == "refused", "deleted after chock bundle wrote it"
    _switch(repo, monkeypatch, "status", "--adopt")
    assert judge() == "allowed"
    assert not toggle.record_path(repo / TOGGLE).exists()
    (repo / TOGGLE).write_text(json.dumps({"version": 1, "bundles": {}}))
    assert judge() == "refused", "a file chock bundle never recorded"


def test_the_user_file_is_checked_too(tmp_path: Path, home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _repo, judge = _at_turn_end("claude", tmp_path, home)
    (home / ".chock").mkdir()
    (home / TOGGLE).write_text(json.dumps({"version": 1, "bundles": {BUNDLE_ID: {GUARD_ID: "off"}}}))
    assert judge() == "refused"


def test_a_mismatch_never_switches_a_guard_off_or_on_at_hook_time(tmp_path: Path, home: Path) -> None:
    repo = tmp_path / "r"
    (repo / ".git").mkdir(parents=True)
    (repo / ".chock").mkdir()
    (repo / TOGGLE).write_text(json.dumps({"version": 1, "bundles": {BUNDLE_ID: {GUARD_ID: "off"}}}))
    _path, _scope, toggles, warning = toggle.load(repo)
    assert toggle.state(toggles, BUNDLE_ID, GUARD_ID) == toggle.OFF and warning is None


def test_the_cli_refuses_to_build_on_a_file_it_did_not_record(
    tmp_path: Path, home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "r"
    (repo / ".git").mkdir(parents=True)
    (repo / ".chock").mkdir()
    (repo / TOGGLE).write_text(json.dumps({"version": 1, "bundles": {}}))
    monkeypatch.chdir(repo)
    assert cli.main(["off", GUARD_ID, "--bundle", BUNDLE_ID]) == cli.EXIT_USAGE
    assert cli.main(["status", "--adopt"]) == 0
    assert cli.main(["off", GUARD_ID, "--bundle", BUNDLE_ID]) == 0


@pytest.mark.parametrize("client", MERGED_CLIENTS)
def test_an_unreadable_stop_is_refused_by_the_turn_end_check(tmp_path: Path, home: Path, client: str) -> None:
    plugin, repo, commands = build(tmp_path, client)
    (verify,) = [c for c in commands if f'{WRAPPER}" {toggle.VERIFY}' in c]
    env = {**os.environ, **dict.fromkeys(ALL_ROOTS, plugin.as_posix()), "HOME": str(home)}
    proc = run_hook_command(verify, repo, "not json", env=env)
    assert "could not read" in proc.stderr + proc.stdout, (proc.returncode, proc.stdout, proc.stderr)
