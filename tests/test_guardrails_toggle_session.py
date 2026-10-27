"""F17 / D14 A: an `off` is honoured only by a session that started after its file's record last changed."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import client_payloads
import pytest
from bundle_fixtures import BUNDLE_ID, GATE_ID, GUARD_ID
from guardrails_support import MERGED_CLIENTS, any_refused, build, outcomes, set_toggles, shell

from chock.gate.session_log import session_id_of
from chock.guardrails import toggle, toggle_state
from chock.guardrails.plugin import WRAPPER_STATE

RM = "rm -rf /"
START = "--session-start"


@pytest.fixture
def home(tmp_path: Path) -> Path:
    path = tmp_path / "home"
    path.mkdir()
    return path


def _start(commands: list[str], plugin: Path, repo: Path, home: Path, session: str, source: str = "startup"):
    (command,) = [c for c in commands if START in c]
    payload = {"hook_event_name": "SessionStart", "session_id": session, "cwd": str(repo), "source": source}
    (proc,) = outcomes([command], plugin, repo, payload, home)
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    return proc


@pytest.mark.parametrize("client", MERGED_CLIENTS)
def test_an_off_written_during_the_session_waits_for_the_next_session(tmp_path: Path, home: Path, client: str) -> None:
    plugin, repo, commands = build(tmp_path, client)
    mine = client_payloads.in_session(shell(client, repo, RM), "one")
    assert any_refused(commands, plugin, repo, mine, home), "on by default"
    set_toggles(repo, {BUNDLE_ID: {GUARD_ID: "off"}})  # the F17 forgery: a file with a matching record
    assert any_refused(commands, plugin, repo, mine, home), "the session that saw no file stays on"
    assert not any_refused(commands, plugin, repo, client_payloads.in_session(mine, "two"), home), (
        "the next session honours it"
    )


def test_a_session_keeps_the_off_it_started_with_and_ignores_every_later_edit(tmp_path: Path, home: Path) -> None:
    plugin, repo, commands = build(tmp_path, "claude")
    mine = client_payloads.in_session(shell("claude", repo, RM), "one")
    set_toggles(repo, {BUNDLE_ID: {GUARD_ID: "off"}})
    assert not any_refused(commands, plugin, repo, mine, home), "off before the session: honoured"
    set_toggles(repo, {BUNDLE_ID: {GUARD_ID: "off", GATE_ID: "off"}})
    procs = outcomes(commands, plugin, repo, mine, home)
    assert any_refused(commands, plugin, repo, mine, home), "the record moved: every member is on again"
    assert any("changed during this session" in p.stderr for p in procs)
    assert not any_refused(commands, plugin, repo, client_payloads.in_session(mine, "two"), home)


def test_the_user_file_binds_the_same_way(tmp_path: Path, home: Path) -> None:
    plugin, repo, commands = build(tmp_path, "claude")
    outside = tmp_path / "scratch"
    outside.mkdir()
    mine = client_payloads.in_session(shell("claude", outside, RM), "one")
    assert any_refused(commands, plugin, outside, mine, home)
    set_toggles(home, {BUNDLE_ID: {GUARD_ID: "off"}})
    assert any_refused(commands, plugin, outside, mine, home)
    assert not any_refused(commands, plugin, outside, client_payloads.in_session(mine, "two"), home)


def test_a_session_start_lists_every_member_that_is_off_by_scope(tmp_path: Path, home: Path) -> None:
    plugin, repo, commands = build(tmp_path, "claude")
    quiet = _start(commands, plugin, repo, home, "quiet")
    assert quiet.stdout.strip() in ("", "{}"), quiet.stdout
    set_toggles(repo, {BUNDLE_ID: {GUARD_ID: "off"}})
    set_toggles(home, {BUNDLE_ID: {GATE_ID: "off"}})
    out = json.loads(_start(commands, plugin, repo, home, "one").stdout)["hookSpecificOutput"]["additionalContext"]
    assert f"repo ({repo / toggle.FILENAME}): {BUNDLE_ID}/{GUARD_ID}" in out
    assert f"user ({home / toggle.FILENAME}) (not applied here: the repository's own file governs): " in out
    assert f"{BUNDLE_ID}/{GATE_ID}" in out
    assert "not a security boundary" in out


def test_a_session_start_binds_the_session_and_a_compaction_does_not_rebind_it(tmp_path: Path, home: Path) -> None:
    plugin, repo, commands = build(tmp_path, "claude")
    mine = client_payloads.in_session(shell("claude", repo, RM), "one")
    _start(commands, plugin, repo, home, "one")
    set_toggles(repo, {BUNDLE_ID: {GUARD_ID: "off"}})
    _start(commands, plugin, repo, home, "one", source="compact")
    assert any_refused(commands, plugin, repo, mine, home), "a compaction is not a new session"
    _start(commands, plugin, repo, home, "one", source="resume")
    assert not any_refused(commands, plugin, repo, mine, home), "a resumed session starts again"


def test_a_client_without_a_session_id_honours_no_off_until_a_session_start(tmp_path: Path, home: Path) -> None:
    plugin, repo, commands = build(tmp_path, "claude")
    nameless = shell("claude", repo, RM)
    set_toggles(repo, {BUNDLE_ID: {GUARD_ID: "off"}})
    assert any_refused(commands, plugin, repo, nameless, home), "no id to bind: every member stays on"


@pytest.mark.parametrize(
    "raw",
    [
        {"session_id": "abc-1"},
        {"session_id": "../../etc/x"},
        {"session_id": ".hidden"},
        {"session_id": "x" * 300},
        {"session_id": ""},
        {},
    ],
)
def test_the_session_id_is_the_one_the_session_log_keeps(raw: dict) -> None:
    event = SimpleNamespace(session_id=raw.get("session_id"), raw=raw)
    assert toggle.session_id(json.dumps(raw).encode()) == session_id_of(event)


def test_a_change_of_directory_does_not_start_a_new_binding(tmp_path: Path, home: Path) -> None:
    plugin, repo, commands = build(tmp_path, "claude")
    outside = tmp_path / "scratch"
    outside.mkdir()
    assert any_refused(commands, plugin, repo, client_payloads.in_session(shell("claude", repo, RM), "one"), home)
    set_toggles(home, {BUNDLE_ID: {GUARD_ID: "off"}})
    assert any_refused(commands, plugin, outside, client_payloads.in_session(shell("claude", outside, RM), "one"), home)


def test_the_plugin_carries_the_state_module_beside_its_wrapper(tmp_path: Path) -> None:
    plugin, _repo, _commands = build(tmp_path, "claude")
    shipped = (plugin / WRAPPER_STATE).read_text(encoding="utf-8")
    assert shipped == Path(toggle_state.__file__).read_text(encoding="utf-8")
