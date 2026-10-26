"""`chock status --verify-log`: log-derived text is inert on screen, and a kept head can name the log it came from."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from chock.gate.runner import chain, journal
from chock.lifecycle import status_main

ESC = "\x1b"


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    folder = tmp_path / "home"
    folder.mkdir()
    monkeypatch.setenv("HOME", str(folder))
    monkeypatch.setenv("USERPROFILE", str(folder))
    return folder


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    folder = tmp_path / "repo"
    (folder / ".git").mkdir(parents=True)
    return folder


def _log(repo: Path) -> Path:
    return repo / ".chock" / "log" / "gate-events.jsonl"


def _text(repo: Path, capsys: pytest.CaptureFixture[str], *extra: str) -> tuple[int, str]:
    capsys.readouterr()
    code = status_main(["--repo", str(repo), "--verify-log", "--route", "sync", *extra])
    return code, capsys.readouterr().out


def test_log_controlled_text_never_reaches_the_terminal_raw(repo: Path, home: Path, capsys) -> None:
    journal.log_append(_log(repo), {"policy_id": "p"})
    with _log(repo).open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"unchained": f"\r{ESC}[2K intact{ESC}]52;c;AAAA\x07"}) + "\n")

    code, out = _text(repo, capsys)

    assert code == 1
    assert ESC not in out
    assert "\r" not in out
    assert "\x07" not in out
    assert "\\x1b[2K" in out


def test_a_folder_label_and_chain_start_are_inert(repo: Path, home: Path, capsys) -> None:
    folder = home / ".chock" / "log" / f"a{ESC}[2Kb"
    folder.mkdir(parents=True)
    line = json.dumps({"prev": f"{ESC}[8m", "seq": 3, "policy_id": "p"})
    (folder / "events.jsonl").write_text(line + "\n", encoding="utf-8")

    capsys.readouterr()
    status_main(["--repo", str(repo), "--verify-log", "--route", "plugin"])

    assert ESC not in capsys.readouterr().out


def test_a_kept_head_naming_its_log_is_confirmed_only_there(repo: Path, home: Path, capsys) -> None:
    for i in range(3):
        journal.log_append(_log(repo), {"policy_id": "p", "i": i})
    lines = _log(repo).read_bytes().splitlines()
    kept = f"2:{chain.log_line_hash(lines[2])}"
    fake = home / ".chock" / "log" / "x" / "events.jsonl"
    fake.parent.mkdir(parents=True)
    fake.write_bytes(lines[2] + b"\n")

    code, out = _text(repo, capsys, "--route", "plugin", "--head", f"{kept}@~/.chock/log/gate-events.jsonl")
    assert (code, "NOT found" in out) == (1, True)

    code, out = _text(repo, capsys, "--head", f"{kept}@.chock/log/gate-events.jsonl")
    assert (code, "confirmed in .chock/log/gate-events.jsonl" in out) == (0, True)


def test_the_verify_output_names_each_log_in_its_head_and_the_anchor_limit(repo: Path, home: Path, capsys) -> None:
    journal.log_append(_log(repo), {"policy_id": "p"})

    _, out = _text(repo, capsys)

    assert "@.chock/log/gate-events.jsonl" in out
    assert "outside anything it can write" in out
