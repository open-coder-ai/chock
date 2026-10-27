"""The turn-end check also refuses a Stop in a session during which a toggle file's record changed to switch a member off."""

from __future__ import annotations

from pathlib import Path

import pytest
from bundle_fixtures import GATE_ID, GUARD_ID
from guardrails_support import MERGED_CLIENTS
from test_guardrails_turn_end import _at_turn_end, _switch


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "home"
    path.mkdir()
    monkeypatch.setenv("HOME", str(path))
    monkeypatch.setenv("USERPROFILE", str(path))
    return path


@pytest.mark.parametrize("client", MERGED_CLIENTS)
def test_a_record_changed_during_the_session_refuses_its_turn_end(
    tmp_path: Path, home: Path, client: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, judge = _at_turn_end(client, tmp_path, home)
    assert judge() == "allowed", "no file when the session began"
    _switch(repo, monkeypatch, "off", GUARD_ID)  # a matching record, as an agent's script can write it
    assert judge() == "refused", "the record changed during the session"
    assert judge("s2") == "allowed", "a session that began after the change"
    _switch(repo, monkeypatch, "on", GUARD_ID)
    assert judge("s2") == "allowed", "a change that switches nothing off loosens nothing"
    _switch(repo, monkeypatch, "off", GATE_ID)
    assert judge("s2") == "refused"
