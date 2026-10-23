"""`chock install` prints what removes a build: the plugin, then its folder, then the shared marketplace (IR-12)."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from install_fixtures import make_catalog, selection, write_selection

from chock.install import cli, package, place, steps

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git required")
#: Clients whose remove command chock could not confirm from the client's docs or a live run; they print no removal.
UNCONFIRMED = {"codex", "antigravity", "kimi-code"}
WITH_REMOVE = [c for c in package.settings()["clients"] if c not in UNCONFIRMED]
MARKETPLACE_CLIENTS = [c for c in WITH_REMOVE if package.client(c)["layout"] == place.MARKETPLACE]
TOKENS = {
    "__DEST__": "/d",
    "__PLUGIN_DIR__": "/d/claude/chock-guardrails",
    "__PLUGIN__": "chock-guardrails",
    "__MARKETPLACE__": "chock-local",
}


def _text(client: str) -> list[str]:
    return [s.text or " ".join(s.command or []) for s in steps.render_remove(client, TOKENS)]


def test_exactly_the_unconfirmed_clients_have_no_removal() -> None:
    assert {c for c in package.settings()["clients"] if "remove" not in package.client(c)} == UNCONFIRMED


@pytest.mark.parametrize("client", WITH_REMOVE)
def test_every_removal_names_the_build_folder_and_fills_every_token(client: str) -> None:
    lines = _text(client)
    assert any("/d/claude/chock-guardrails" in line for line in lines), "the build folder is named"
    assert not any("__" in line for line in lines), "every token is filled"


@pytest.mark.parametrize("client", MARKETPLACE_CLIENTS)
def test_the_shared_marketplace_is_removed_only_on_the_readers_say_so(client: str) -> None:
    rendered = steps.render_remove(client, TOKENS)
    removing = [s for s in rendered if "marketplace remove" in s.text]
    assert len(removing) == 1
    assert "Only if no other chock build" in removing[0].text
    assert not any(s.command and "marketplace" in s.command and "remove" in s.command for s in rendered)


def test_claude_code_removes_the_plugin_then_the_folder_then_the_marketplace() -> None:
    lines = _text("claude-code")
    assert lines[0] == "claude plugin uninstall chock-guardrails@chock-local"
    assert "Delete the build folder /d/claude/chock-guardrails" in lines[1]
    assert lines[2].endswith("`claude plugin marketplace remove chock-local`. Otherwise leave it registered.")
    assert len(lines) == 3


def test_copilot_says_its_uninstall_only_disables() -> None:
    assert "only disables" in _text("copilot")[0]


def test_install_prints_the_removal_after_the_install_steps(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    root, ref = make_catalog(tmp_path)
    base = selection(root, ref)
    picks = [{"from": "catalog", **p} for p in base["policies"]]
    data = {**base, "schema": 2, "client": "claude-code", "bundle": {"version": "2.0.0"}, "policies": picks}
    path = write_selection(tmp_path / "chock.selection.yaml", data)
    assert cli.main(["--selection", str(path), "--allow-source", data["catalog"]["source"]]) == 0
    out = capsys.readouterr().out
    assert out.index("Next:") < out.index("To remove it:")
    assert "  claude plugin uninstall chock-guardrails@chock-local" in out
    assert "Delete the build folder" in out
