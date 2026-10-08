"""`chock bundle on|off|status`: the only writers of the toggle file, round trip, and what status shows."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from conftest import init_repo

from chock.guardrails import cli, toggle
from chock.guardrails.plugin import MEMBERS
from chock.install import package, place

B, P, Q = "chock-guardrails", "block-destructive-commands", "block-invisible-unicode"


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "home"
    path.mkdir()
    monkeypatch.setenv("HOME", str(path))
    monkeypatch.setenv("USERPROFILE", str(path))
    return path


def _installed(client: str, name: str, members: dict[str, str]) -> Path:
    """A chock-built plugin as install leaves it: its marker and its member list."""
    folder = place.plugin_dir(client, place.default_dest(client), name)
    (folder / "scripts").mkdir(parents=True)
    marker = {"schema": 2, "client": client, "bundle": {"name": name}, "policies": [{"id": i} for i in members]}
    (folder / package.MARKER).write_text(json.dumps(marker), encoding="utf-8")
    listed = {"bundle": name, "members": [{"id": i, "label": label} for i, label in members.items()]}
    (folder / MEMBERS).write_text(json.dumps(listed), encoding="utf-8")
    return folder


@pytest.fixture
def repo(tmp_path: Path, home: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    (tmp_path / "work").mkdir()
    path = init_repo(tmp_path / "work")
    _installed("claude-code", B, {P: "blocks: refuses a destructive command", Q: "blocks: refuses hidden text"})
    monkeypatch.chdir(path)
    return path


def _doc(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_off_then_on_round_trips_at_repo_scope(repo: Path, capsys: pytest.CaptureFixture) -> None:
    assert cli.main(["off", P]) == 0
    assert _doc(repo / toggle.FILENAME) == {"version": 1, "bundles": {B: {P: "off"}}}
    assert "check --only baseline" in capsys.readouterr().out
    assert cli.main(["status"]) == 0
    out = capsys.readouterr().out
    assert re.search(rf"{P} +off  blocks: refuses a destructive command", out)
    assert re.search(rf"{Q} +on   blocks: refuses hidden text", out)
    assert cli.main(["on", P]) == 0
    assert _doc(repo / toggle.FILENAME)["bundles"][B][P] == "on"
    toggle.parse((repo / toggle.FILENAME).read_text(encoding="utf-8"))


def test_user_scope_writes_the_home_file_and_says_the_repo_governs(
    repo: Path, home: Path, capsys: pytest.CaptureFixture
) -> None:
    assert cli.main(["off", P]) == 0
    capsys.readouterr()
    assert cli.main(["off", Q, "--scope", "user"]) == 0
    assert _doc(home / toggle.FILENAME) == {"version": 1, "bundles": {B: {Q: "off"}}}
    assert "governs this repository" in capsys.readouterr().out


def test_outside_a_repository_the_default_scope_is_user(tmp_path: Path, home: Path, monkeypatch) -> None:
    _installed("cursor", B, {P: "blocks"})
    outside = tmp_path / "plain"
    outside.mkdir()
    monkeypatch.chdir(outside)
    assert cli.main(["off", P]) == 0
    assert _doc(home / toggle.FILENAME)["bundles"][B][P] == "off"
    assert cli.main(["off", P, "--scope", "repo"]) == cli.EXIT_USAGE


def test_an_unknown_or_ambiguous_member_needs_a_bundle_name(repo: Path, home: Path) -> None:
    assert cli.main(["off", "not-installed"]) == cli.EXIT_USAGE
    _installed("codex", "second-bundle", {P: "blocks"})
    assert cli.main(["off", P]) == cli.EXIT_USAGE
    assert cli.main(["off", P, "--bundle", "second-bundle"]) == 0
    assert _doc(repo / toggle.FILENAME) == {"version": 1, "bundles": {"second-bundle": {P: "off"}}}


@pytest.mark.parametrize("bad", ["Bad", "x", "../etc", "a b"])
def test_names_that_are_not_ids_are_refused(repo: Path, bad: str) -> None:
    assert cli.main(["off", bad, "--bundle", B]) == cli.EXIT_USAGE
    assert cli.main(["off", P, "--bundle", bad]) == cli.EXIT_USAGE
    assert not (repo / toggle.FILENAME).exists()


def test_an_invalid_or_linked_file_is_never_overwritten(repo: Path, tmp_path: Path) -> None:
    path = repo / toggle.FILENAME
    path.parent.mkdir()
    path.write_text("{broken", encoding="utf-8")
    assert cli.main(["off", P]) == cli.EXIT_USAGE
    assert path.read_text(encoding="utf-8") == "{broken"
    path.unlink()
    (tmp_path / "target.json").write_text('{"version": 1, "bundles": {}}', encoding="utf-8")
    path.symlink_to(tmp_path / "target.json")
    assert cli.main(["off", P]) == cli.EXIT_USAGE
    assert _doc(tmp_path / "target.json") == {"version": 1, "bundles": {}}


def test_the_built_in_protection_cannot_be_switched(repo: Path) -> None:
    assert cli.main(["off", "chock-guardrails-protect", "--bundle", B]) == cli.EXIT_USAGE


def test_status_warns_that_an_invalid_file_keeps_everything_on(repo: Path, capsys: pytest.CaptureFixture) -> None:
    (repo / ".chock").mkdir()
    (repo / toggle.FILENAME).write_text(json.dumps({"version": 1, "bundles": {B: {P: "nope"}}}), encoding="utf-8")
    assert cli.main(["status"]) == 0
    out = capsys.readouterr().out
    assert "every guardrail stays on" in out and re.search(rf"{P} +on ", out)


def test_adopt_refuses_an_invalid_file_and_reset_rewrites_it_all_on(repo: Path, capsys: pytest.CaptureFixture) -> None:
    path = repo / toggle.FILENAME
    path.parent.mkdir()
    path.write_text("{}", encoding="utf-8")
    assert cli.main(["status", "--adopt"]) == cli.EXIT_USAGE
    err = capsys.readouterr().err
    assert "exactly the keys ['bundles', 'version'], got []" in err and cli.RESET in err
    assert toggle.recorded(path) is None and path.read_text(encoding="utf-8") == "{}"
    assert cli.main(["off", P]) == cli.EXIT_USAGE
    assert cli.main(["status", "--adopt", "--reset"]) == 0
    assert _doc(path) == {"version": 1, "bundles": {}} and toggle.drift(path) is None
    assert cli.main(["off", P]) == 0
    assert _doc(path) == {"version": 1, "bundles": {B: {P: "off"}}}


def test_an_adopted_invalid_file_names_the_reset_when_switching(repo: Path, capsys: pytest.CaptureFixture) -> None:
    path = repo / toggle.FILENAME
    path.parent.mkdir()
    path.write_text("{}", encoding="utf-8")
    cli.record(path)
    assert cli.main(["off", P]) == cli.EXIT_USAGE
    assert cli.RESET in capsys.readouterr().err
    assert cli.main(["status", "--adopt", "--reset"]) == 0
    assert cli.main(["off", P]) == 0


def test_reset_only_rewrites_invalid_files_and_never_switches_off(
    repo: Path, home: Path, tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    assert cli.main(["off", Q, "--scope", "user"]) == 0
    user = home / toggle.FILENAME
    user.write_text(json.dumps({"version": 1, "bundles": {B: {P: "off", Q: "off"}}}), encoding="utf-8")
    path = repo / toggle.FILENAME
    path.parent.mkdir()
    (tmp_path / "target.json").write_text("{}", encoding="utf-8")
    path.symlink_to(tmp_path / "target.json")
    assert cli.main(["status", "--adopt", "--reset"]) == 0
    assert not path.is_symlink() and _doc(path) == {"version": 1, "bundles": {}}
    assert (tmp_path / "target.json").read_text(encoding="utf-8") == "{}"
    assert _doc(user)["bundles"][B] == {P: "off", Q: "off"} and toggle.drift(user) is None
    assert toggle.load(repo)[2] == {}


def test_reset_leaves_a_folder_alone(repo: Path, capsys: pytest.CaptureFixture) -> None:
    (repo / toggle.FILENAME).mkdir(parents=True)
    assert cli.main(["status", "--adopt", "--reset"]) == cli.EXIT_USAGE
    assert "move it aside" in capsys.readouterr().err and (repo / toggle.FILENAME).is_dir()


def test_reset_needs_adopt_and_adopt_still_takes_a_valid_file(repo: Path) -> None:
    with pytest.raises(SystemExit):
        cli.main(["status", "--reset"])
    path = repo / toggle.FILENAME
    path.parent.mkdir()
    path.write_text(json.dumps({"version": 1, "bundles": {B: {P: "off"}}}), encoding="utf-8")
    assert cli.main(["status", "--adopt"]) == 0
    assert toggle.drift(path) is None and toggle.load(repo)[2] == {B: {P: "off"}}
