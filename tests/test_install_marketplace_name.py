"""`chock install --marketplace-name`: the build's local marketplace under a name of the team's own (IR-13)."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import pytest
from install_fixtures import make_catalog
from test_install_claude_plugin import DATA, OFFERED
from test_install_clients import _read, _run, v2
from test_install_command import _stub_claude

from chock.install import claude_plugin, package, place

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git required")
DEFAULT = package.settings()["marketplace"]
CUSTOM = "acme-chock"
MARKETPLACE_CLIENTS = [c for c in package.settings()["clients"] if package.client(c)["layout"] == place.MARKETPLACE]
CLIENTS = list(package.settings()["clients"])


@pytest.fixture
def catalog(tmp_path: Path) -> tuple[Path, str]:
    return make_catalog(tmp_path)


def _build(catalog: tuple[Path, str], tmp_path: Path, client: str, *extra: str) -> int:
    root, ref = catalog
    return _run(tmp_path, v2(root, ref, client), "--dest", str(tmp_path / "market"), *extra)


def _index(dest: Path, client: str) -> dict:
    return _read(dest / package.client(client)["index"][0]["path"])


@pytest.mark.parametrize("client", MARKETPLACE_CLIENTS)
def test_without_the_flag_every_marketplace_is_chock_local(catalog, tmp_path: Path, capsys, client: str) -> None:
    assert _build(catalog, tmp_path, client) == 0
    dest = tmp_path / "market"
    assert _index(dest, client)["name"] == DEFAULT == "chock-local"
    assert _read(dest / place.MARKETPLACE_MARKER)["marketplace"] == DEFAULT
    assert f"@{DEFAULT}" in capsys.readouterr().out or client == "codex"


@pytest.mark.parametrize("client", MARKETPLACE_CLIENTS)
def test_a_custom_name_is_the_manifest_and_marker_name(catalog, tmp_path: Path, client: str) -> None:
    assert _build(catalog, tmp_path, client, "--marketplace-name", CUSTOM) == 0
    dest = tmp_path / "market"
    assert _index(dest, client)["name"] == CUSTOM
    assert _read(dest / place.MARKETPLACE_MARKER)["marketplace"] == CUSTOM


@pytest.mark.parametrize("client", CLIENTS)
def test_a_custom_name_replaces_the_default_in_every_printed_step(catalog, tmp_path: Path, capsys, client: str) -> None:
    assert _build(catalog, tmp_path, client, "--marketplace-name", CUSTOM) == 0
    out = capsys.readouterr().out
    assert DEFAULT not in out, "no next step, removal step or note keeps the default name"
    if client == "claude-code":
        assert f"  claude plugin install chock-guardrails@{CUSTOM}" in out
        assert f"  claude plugin uninstall chock-guardrails@{CUSTOM}" in out
        assert f"`claude plugin marketplace remove {CUSTOM}`" in out
    if client == "copilot":
        assert f"  copilot plugin uninstall chock-guardrails@{CUSTOM}" in out


def test_the_copilot_note_and_the_build_command_name_the_chosen_marketplace(tmp_path: Path) -> None:
    filled = claude_plugin.tokens(tmp_path / "d", "chock-guardrails", "CODE", CUSTOM)
    out = "\n".join(claude_plugin.lines(DATA["build_client"], filled))
    if "copilot" in OFFERED:
        assert f'Marketplace "{CUSTOM}" already registered' in out
        assert f"copilot plugin marketplace remove {CUSTOM}" in out
    assert DEFAULT not in out
    other = next((c for c in OFFERED if c != DATA["build_client"]), None)
    if other:
        text = "\n".join(claude_plugin.lines(other, filled))
        assert f"--client claude-code --marketplace-name {CUSTOM}" in text


def test_the_default_build_command_has_no_flag(tmp_path: Path) -> None:
    filled = claude_plugin.tokens(tmp_path / "d", "chock-guardrails", "CODE", DEFAULT)
    other = next(c for c in OFFERED if c != DATA["build_client"])
    text = "\n".join(claude_plugin.lines(other, filled))
    assert "--client claude-code (then" in text
    assert "--marketplace-name" not in text


@pytest.mark.skipif(os.name == "nt", reason="the stub is a POSIX shell script")
def test_apply_runs_the_commands_with_the_chosen_name(catalog, tmp_path: Path, monkeypatch) -> None:
    log = _stub_claude(tmp_path, monkeypatch)
    assert _build(catalog, tmp_path, "claude-code", "--marketplace-name", CUSTOM, "--apply") == 0
    assert log.read_text(encoding="utf-8").splitlines() == [
        f"plugin marketplace add {(tmp_path / 'market').resolve()}",
        f"plugin install chock-guardrails@{CUSTOM}",
    ]


@pytest.mark.parametrize(
    "bad",
    ["", "Acme", "acme_chock", "acme chock", "-acme", "acme-", "acme--chock", "acme.chock", "../acme", "é", "a" * 65],
)
def test_an_invalid_name_is_refused_and_nothing_is_built(catalog, tmp_path: Path, capsys, bad: str) -> None:
    assert _build(catalog, tmp_path, "claude-code", f"--marketplace-name={bad}") == 1
    assert "not a valid marketplace name" in capsys.readouterr().err
    assert not (tmp_path / "market").exists()


@pytest.mark.parametrize("good", ["a", "acme", "acme-chock", "team-2", "0", "a" * 64])
def test_a_name_of_lowercase_letters_digits_and_single_hyphens_is_accepted(good: str) -> None:
    assert package.marketplace(good) == good


def test_a_marketplace_folder_is_not_renamed_under_the_plugins_installed_from_it(
    catalog, tmp_path: Path, capsys
) -> None:
    assert _build(catalog, tmp_path, "claude-code") == 0
    capsys.readouterr()
    dest = tmp_path / "market"
    assert _build(catalog, tmp_path, "claude-code", "--marketplace-name", CUSTOM) == 1
    err = capsys.readouterr().err
    assert "chock-local marketplace" in err
    assert "--dest" in err
    assert _index(dest, "claude-code")["name"] == DEFAULT
    assert _build(catalog, tmp_path, "claude-code") == 0, "the same name rebuilds"


def test_a_custom_folder_rebuilds_under_its_own_name_only(catalog, tmp_path: Path, capsys) -> None:
    assert _build(catalog, tmp_path, "claude-code", "--marketplace-name", CUSTOM) == 0
    capsys.readouterr()
    assert _build(catalog, tmp_path, "claude-code", "--marketplace-name", CUSTOM) == 0
    assert _build(catalog, tmp_path, "claude-code") == 1
    assert json.loads((tmp_path / "market" / place.MARKETPLACE_MARKER).read_text())["marketplace"] == CUSTOM


def test_three_argument_tokens_are_the_default_name_tokens(tmp_path: Path) -> None:
    old = claude_plugin.tokens(tmp_path, "set-two", "sel.yaml")
    assert old == claude_plugin.tokens(tmp_path, "set-two", "sel.yaml", DEFAULT)
    assert old["__MARKETPLACE__"] == DEFAULT
    assert old["__MARKETPLACE_FLAG__"] == ""


def test_place_helpers_default_to_the_default_name(tmp_path: Path) -> None:
    place.check_owned("claude-code", tmp_path / "empty", "set-two")
    (tmp_path / "market").mkdir()
    assert place.write_marketplace("claude-code", tmp_path / "market")
    assert json.loads((tmp_path / "market" / place.MARKETPLACE_MARKER).read_text())["marketplace"] == DEFAULT
