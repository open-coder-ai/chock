"""`chock status` policy table: ids and coverage cells from the repo print inert."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from chock import toggles

ESC = "\x1b"


def test_a_cell_from_the_repo_never_moves_the_cursor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / ".chock").mkdir()
    (tmp_path / ".chock" / "coverage.json").write_text(
        json.dumps({f"p{ESC}[2K\rfake": {f"a{ESC}]52;c;AA\x07": "full"}}), encoding="utf-8"
    )
    monkeypatch.setattr(toggles, "_policy_ids", lambda _root: [f"p{ESC}[2K\rfake"])
    monkeypatch.setattr(toggles, "_find_policy_manifest", lambda *_a: None)
    monkeypatch.setattr(toggles, "policy_status", lambda *_a: {"state": f"on{ESC}[1A", "mandatory": False})

    assert toggles.policies_main(["--repo", str(tmp_path)]) == 0

    out = capsys.readouterr().out
    assert not {ESC, "\r", "\x07"} & set(out)
    assert "\\x1b[2K" in out
