"""The turn-end check: a toggle file that differs from what `chock bundle` recorded refuses the Stop, in every format."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from bundle_fixtures import ALL_ROOTS, BUNDLE_ID, GUARD_ID
from conftest import run_hook_command
from guardrails_support import MERGED_CLIENTS, TOGGLE, any_refused, build, outcomes, refused, set_toggles, shell

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
def test_a_deletion_passes_and_drops_the_stale_record(
    tmp_path: Path, home: Path, client: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Codex witness 2026-10-07: absent is all on, so a deletion only tightens and never refuses a turn end."""
    repo, judge = _at_turn_end(client, tmp_path, home)
    _switch(repo, monkeypatch, "off", GUARD_ID)
    (repo / TOGGLE).unlink()
    capsys.readouterr()
    _switch(repo, monkeypatch, "status")
    assert f"{toggle.DELETED}; every member is on" in capsys.readouterr().out, "status still reports it"
    assert judge() == "allowed"
    assert not toggle.record_path(repo / TOGGLE).exists(), "the stale record is dropped"
    (repo / TOGGLE).write_text(json.dumps({"version": 1, "bundles": {}}))
    assert judge() == "refused", "a file chock bundle never recorded"


def _changed(path: Path) -> None:
    path.write_text(json.dumps({"version": 1, "bundles": {BUNDLE_ID: {GUARD_ID: "on"}}}))


def _unreadable(path: Path) -> None:
    path.unlink()
    path.mkdir()


def _linked(path: Path) -> None:
    other = path.with_name("other.json")
    _changed(other)
    path.unlink()
    path.symlink_to(other)


def _dangling(path: Path) -> None:
    path.unlink()
    path.symlink_to(path.with_name("gone.json"))


@pytest.mark.parametrize("change", [_changed, _unreadable, _linked, _dangling])
def test_every_other_drift_still_refuses(tmp_path: Path, home: Path, monkeypatch: pytest.MonkeyPatch, change) -> None:
    repo, judge = _at_turn_end("claude", tmp_path, home)
    _switch(repo, monkeypatch, "off", GUARD_ID)
    change(repo / TOGGLE)
    assert judge() == "refused"
    assert judge() == "refused", "a refusal drops no record"
    assert toggle.record_path(repo / TOGGLE).exists()


def test_a_deleted_user_file_passes_too(tmp_path: Path, home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _repo, judge = _at_turn_end("claude", tmp_path, home)
    monkeypatch.chdir(tmp_path)
    assert cli.main(["off", GUARD_ID, "--bundle", BUNDLE_ID, "--scope", "user"]) == 0
    (home / TOGGLE).unlink()
    assert judge() == "allowed"
    assert not toggle.record_path(home / TOGGLE).exists()


def _user_file(home: Path, members: dict[str, str] | None) -> None:
    """The user-scope toggle file as `chock bundle` records it, or none."""
    if members is not None:
        set_toggles(home, {BUNDLE_ID: members})


@pytest.mark.parametrize(
    ("user", "verdict"),
    [
        (None, "allowed"),
        ({GUARD_ID: "on"}, "allowed"),
        ({GUARD_ID: "off"}, "refused"),
        ({"demo-write-gate": "off"}, "refused"),
    ],
)
def test_a_repo_deletion_that_hands_control_to_a_looser_user_file_still_refuses(
    tmp_path: Path, home: Path, monkeypatch: pytest.MonkeyPatch, user: dict[str, str] | None, verdict: str
) -> None:
    """Orchestrator review: with the repo file gone the user file governs the repo, so deleting it can loosen."""
    repo, judge = _at_turn_end("claude", tmp_path, home)
    _switch(repo, monkeypatch, "on", GUARD_ID)
    _user_file(home, user)
    (repo / TOGGLE).unlink()
    assert judge() == verdict
    assert toggle.record_path(repo / TOGGLE).exists() == (verdict == "refused"), "a refusal keeps the record"


def test_the_refusal_names_the_user_file_and_what_it_switches_off(
    tmp_path: Path, home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo, _judge = _at_turn_end("claude", tmp_path, home)
    _switch(repo, monkeypatch, "on", GUARD_ID)
    _user_file(home, {GUARD_ID: "off"})
    (repo / TOGGLE).unlink()
    assert toggle.turn_end_drifted([repo]) == [
        f"{repo / TOGGLE}: deleting it hands control to {home / TOGGLE}, which switches {BUNDLE_ID}/{GUARD_ID} off"
    ]
    capsys.readouterr()
    _switch(repo, monkeypatch, "status")
    assert f"warning: {repo / TOGGLE}: deleting it hands control to" in capsys.readouterr().out


def test_a_repo_deletion_onto_an_unrecorded_user_file_refuses(
    tmp_path: Path, home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, _judge = _at_turn_end("claude", tmp_path, home)
    _switch(repo, monkeypatch, "on", GUARD_ID)
    set_toggles(home, {BUNDLE_ID: {}}, recorded=False)
    (repo / TOGGLE).unlink()
    assert f"{repo / TOGGLE}: deleting it hands control to" in toggle.turn_end_drifted([repo])[0]


def _two_roots(tmp_path: Path, home: Path):
    """A Cursor Stop naming two workspace roots and no `cwd`, its hook started outside both."""
    plugin, repo, commands = build(tmp_path, "cursor")
    (verify,) = [c for c in commands if f'{WRAPPER}" {toggle.VERIFY}' in c]
    first = tmp_path / "first"
    (first / ".git").mkdir(parents=True)
    payload = {**_stop("cursor", repo), "workspace_roots": [str(first), str(repo)]}
    del payload["cwd"]

    def judge() -> tuple[str, str]:
        (proc,) = outcomes([verify], plugin, tmp_path, payload, home)
        return _verdict(proc), proc.stdout + proc.stderr

    return first, repo, judge


def test_of_several_workspace_roots_each_is_checked(
    tmp_path: Path, home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first, repo, judge = _two_roots(tmp_path, home)
    _switch(repo, monkeypatch, "off", GUARD_ID)
    assert judge()[0] == "allowed"
    _changed(repo / TOGGLE)
    verdict, said = judge()
    assert verdict == "refused", "the drift is in the second root"
    assert str(repo / TOGGLE) in said and str(first / TOGGLE) not in said
    set_toggles(first, {BUNDLE_ID: {GUARD_ID: "off"}}, recorded=False)
    _verdict_both, said = judge()
    assert str(repo / TOGGLE) in said and str(first / TOGGLE) in said, "each root's finding, under its own file"


def test_a_deletion_in_a_second_workspace_root_passes(
    tmp_path: Path, home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _first, repo, judge = _two_roots(tmp_path, home)
    _switch(repo, monkeypatch, "off", GUARD_ID)
    (repo / TOGGLE).unlink()
    assert judge()[0] == "allowed"
    assert not toggle.record_path(repo / TOGGLE).exists()


def test_the_user_file_is_checked_too(tmp_path: Path, home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _repo, judge = _at_turn_end("claude", tmp_path, home)
    (home / ".chock").mkdir()
    (home / TOGGLE).write_text(json.dumps({"version": 1, "bundles": {BUNDLE_ID: {GUARD_ID: "off"}}}))
    assert judge() == "refused"


def test_a_file_that_differs_from_its_record_switches_nothing_off(tmp_path: Path, home: Path) -> None:
    repo = tmp_path / "r"
    (repo / ".git").mkdir(parents=True)
    set_toggles(repo, {BUNDLE_ID: {GUARD_ID: "off"}}, recorded=False)
    _path, _scope, toggles, warning = toggle.load(repo)
    assert toggles == {} and toggle.DRIFTED in (warning or "")
    set_toggles(repo, {BUNDLE_ID: {GUARD_ID: "off"}})
    _path, _scope, toggles, warning = toggle.load(repo)
    assert toggle.state(toggles, BUNDLE_ID, GUARD_ID) == toggle.OFF and warning is None


@pytest.mark.parametrize("client", MERGED_CLIENTS)
def test_an_agent_written_off_is_ignored_at_hook_time_until_a_person_adopts_it(
    tmp_path: Path, home: Path, client: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    plugin, repo, commands = build(tmp_path, client)
    payload = shell(client, repo, "rm -rf /")
    set_toggles(repo, {BUNDLE_ID: {GUARD_ID: "off"}}, recorded=False)
    procs = outcomes(commands, plugin, repo, payload, home)
    assert any(refused(p) for p in procs), "an unrecorded off switches nothing off"
    assert any(toggle.DRIFTED in p.stderr for p in procs)
    _switch(repo, monkeypatch, "status", "--adopt")
    assert not any_refused(commands, plugin, repo, payload, home), "honoured once the person adopted it"


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
