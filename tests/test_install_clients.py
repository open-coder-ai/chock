"""`chock install --client`: each client's folder, layout, index, labels, warnings and steps; bundles coexist."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import pytest
from bundle_fixtures import ADVISORY_ID, GATE_ID, GUARD_ID
from install_fixtures import make_catalog, selection, write_selection

from chock.install import cli, package, place
from chock.install import selection as sel

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git required")
CLIENTS = ("claude-code", "cursor", "codex", "copilot", "devin")
#: (plugin folder under the dest, the plugin manifest inside it, the index files at the dest root).
TREE = {
    "claude-code": ("claude/chock-guardrails", ".claude-plugin/plugin.json", [".claude-plugin/marketplace.json"]),
    "copilot": ("claude/chock-guardrails", ".claude-plugin/plugin.json", [".claude-plugin/marketplace.json"]),
    "codex": ("codex/chock-guardrails", ".codex-plugin/plugin.json", [".agents/plugins/marketplace.json"]),
    "cursor": ("chock-guardrails", ".cursor-plugin/plugin.json", []),
    "devin": ("chock-guardrails", ".devin-plugin/plugin.json", []),
}
# Clients chock has not witnessed an install in; Claude Code and Codex are witnessed.
UNWITNESSED = ("copilot", "cursor", "devin")
BINARY = {"claude-code": "claude", "copilot": "copilot", "codex": "codex", "devin": "devin"}


@pytest.fixture
def catalog(tmp_path: Path) -> tuple[Path, str]:
    return make_catalog(tmp_path)


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A throwaway HOME, so every default folder lands in the test's own directory."""
    path = tmp_path / "home"
    path.mkdir()
    monkeypatch.setenv("HOME", str(path))
    monkeypatch.setenv("USERPROFILE", str(path))
    return path


def v2(
    root: Path, ref: str, client: str, ids: tuple[str, ...] = (GUARD_ID, GATE_ID, ADVISORY_ID), **bundle: str
) -> dict:
    base = selection(root, ref, ids)
    picks = [{"from": "catalog", **p} for p in base["policies"]]
    return {**base, "schema": 2, "client": client, "bundle": {"version": "2.0.0", **bundle}, "policies": picks}


def _run(tmp_path: Path, data: dict, *extra: str) -> int:
    path = write_selection(tmp_path / "chock.selection.yaml", data)
    return cli.main(["--selection", str(path), "--allow-source", data["catalog"]["source"], *extra])


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("client", CLIENTS)
def test_each_client_builds_its_own_layout_and_index_in_its_own_default_folder(
    catalog, tmp_path: Path, home: Path, client: str, capsys
) -> None:
    root, ref = catalog
    assert _run(tmp_path, v2(root, ref, client)) == 0
    dest = place.default_dest(client)
    assert dest == home / Path(package.client(client)["dest"]).relative_to("~")
    folder, manifest_rel, indexes = TREE[client]
    plugin = dest / folder
    manifest = _read(plugin / manifest_rel)
    assert manifest["name"] == "chock-guardrails"
    assert manifest["version"].startswith("2.0.0+")
    assert manifest["version"] == f"2.0.0+{sel.digest(v2(root, ref, client))[:12]}"
    assert _read(plugin / package.MARKER)["client"] == client
    for policy_id in (GUARD_ID, GATE_ID, ADVISORY_ID):
        assert (plugin / "skills" / policy_id / "SKILL.md").is_file()
    for index in indexes:
        listed = _read(dest / index)["plugins"]
        assert [p["name"] for p in listed] == ["chock-guardrails"]
    if package.client(client)["layout"] == place.MARKETPLACE:
        assert _read(dest / place.MARKETPLACE_MARKER) == {"client": client, "marketplace": "chock-local"}
    else:
        assert not (dest / place.MARKETPLACE_MARKER).exists()
    assert f"for {package.client(client)['name']} in {plugin.resolve()}" in capsys.readouterr().out


def test_cursor_installs_into_its_local_plugins_folder(catalog, tmp_path: Path, home: Path) -> None:
    root, ref = catalog
    assert _run(tmp_path, v2(root, ref, "cursor", name="my-set")) == 0
    assert (home / ".cursor" / "plugins" / "local" / "my-set" / ".cursor-plugin" / "plugin.json").is_file()


def test_the_codex_index_is_the_documented_local_marketplace(catalog, tmp_path: Path, home: Path) -> None:
    root, ref = catalog
    assert _run(tmp_path, v2(root, ref, "codex")) == 0
    index = _read(place.default_dest("codex") / ".agents" / "plugins" / "marketplace.json")
    assert index == {
        "name": "chock-local",
        "plugins": [
            {
                "name": "chock-guardrails",
                "source": {"source": "local", "path": "./codex/chock-guardrails"},
                "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
                "category": "Productivity",
            }
        ],
    }


def test_the_flag_overrides_the_selections_client_and_the_marker_records_it(catalog, tmp_path: Path, home) -> None:
    root, ref = catalog
    assert _run(tmp_path, selection(root, ref), "--client", "devin") == 0
    assert _read(place.default_dest("devin") / "chock-guardrails" / package.MARKER)["client"] == "devin"
    assert not place.default_dest("claude-code").exists()


@pytest.mark.parametrize(
    ("client", "guard_says", "gate_says"),
    [
        ("claude-code", "refuses a matched shell command", "blocks on an agent's file writes and at turn end"),
        ("cursor", "refuses a matched shell command", "blocks on an agent's file writes and at turn end"),
        (
            "codex",
            "once its hooks are trusted in /hooks: refuses a matched shell command",
            "once its hooks are trusted in /hooks: blocks on an agent's file writes",
        ),
        ("copilot", "refuses a matched shell command", "blocks at turn end only; the write itself is not judged"),
        (
            "devin",
            "best-effort, fails open: refuses a matched shell command",
            "best-effort, fails open: blocks at turn end only",
        ),
    ],
)
def test_each_label_carries_the_clients_own_qualifier(
    catalog, tmp_path: Path, home, capsys, client: str, guard_says: str, gate_says: str
) -> None:
    root, ref = catalog
    assert _run(tmp_path, v2(root, ref, client)) == 0
    out = capsys.readouterr().out
    assert f"Each policy, on {package.client(client)['name']}:" in out
    lines = {line.split()[0]: line for line in out.splitlines() if line.startswith("  demo-")}
    assert guard_says in lines[GUARD_ID]
    assert gate_says in lines[GATE_ID]
    assert "advisory only" in lines[ADVISORY_ID] and "fails open" not in lines[ADVISORY_ID]


@pytest.mark.parametrize("client", CLIENTS)
def test_client_warnings_say_untested_for_every_unwitnessed_client(catalog, tmp_path, home, capsys, client) -> None:
    root, ref = catalog
    assert _run(tmp_path, v2(root, ref, client)) == 0
    out = capsys.readouterr().out
    assert ("warning: Untested: chock has not witnessed an install" in out) == (client in UNWITNESSED)
    assert ("trust them in /hooks" in out) == (client == "codex")
    assert ("fails open: a hook that errors" in out) == (client == "devin")
    assert ("only at turn end" in out) == (client in ("copilot", "devin"))
    assert ("Allow Local Plugin Imports" in out) == (client == "cursor")


@pytest.mark.parametrize("client", CLIENTS)
def test_the_steps_are_the_clients_own(catalog, tmp_path: Path, home, capsys, client: str) -> None:
    root, ref = catalog
    assert _run(tmp_path, v2(root, ref, client)) == 0
    out = capsys.readouterr().out
    dest = place.default_dest(client).resolve()
    plugin = dest / TREE[client][0]
    expected = {
        "claude-code": [f"claude plugin marketplace add {dest}", "claude plugin install chock-guardrails@chock-local"],
        "copilot": [f"copilot plugin marketplace add {dest}", "copilot plugin install chock-guardrails@chock-local"],
        "codex": [f"codex plugin marketplace add {dest}", "trust its hooks in /hooks"],
        "cursor": [f"Cursor loads {plugin} as a local plugin", "There is no command to run"],
        "devin": [f"devin plugins install --local {plugin}"],
    }[client]
    for line in expected:
        assert line in out
    if client == "copilot":
        assert json.dumps(str(plugin)) + ": true" in out, "the VS Code snippet is printed, with the folder quoted"


def _stub(tmp_path: Path, monkeypatch, name: str) -> Path:
    bin_dir, log = tmp_path / "bin", tmp_path / f"{name}.log"
    bin_dir.mkdir(exist_ok=True)
    stub = bin_dir / name
    stub.write_text(f'#!/bin/sh\necho "$*" >> "{log}"\n', encoding="utf-8")
    stub.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    return log


def _files(root: Path) -> set[Path]:
    return {p.relative_to(root) for p in root.rglob("*") if p.is_file()}


@pytest.mark.skipif(os.name == "nt", reason="the stub is a POSIX shell script")
@pytest.mark.parametrize("client", sorted(BINARY))
def test_apply_runs_only_the_clients_commands_and_writes_no_settings(
    catalog, tmp_path: Path, home: Path, monkeypatch, client: str
) -> None:
    root, ref = catalog
    log = _stub(tmp_path, monkeypatch, BINARY[client])
    assert _run(tmp_path, v2(root, ref, client), "--apply") == 0
    dest = place.default_dest(client).resolve()
    plugin = dest / TREE[client][0]
    tokens = {"__DEST__": str(dest), "__PLUGIN_DIR__": str(plugin), "__PLUGIN__": "chock-guardrails"}
    expected = []
    for step in package.client(client)["steps"]:
        if "command" in step:
            line = " ".join(step["command"][1:]).replace("__MARKETPLACE__", "chock-local")
            for token, value in tokens.items():
                line = line.replace(token, value)
            expected.append(line)
    assert expected
    assert log.read_text(encoding="utf-8").splitlines() == expected
    outside = {p for p in _files(home) if not (home / p).resolve().is_relative_to(dest)}
    assert outside == set(), "chock wrote outside its own folder (a client's settings?)"


def test_apply_for_cursor_runs_nothing_and_succeeds(catalog, tmp_path: Path, home: Path, monkeypatch, capsys) -> None:
    root, ref = catalog
    monkeypatch.setattr(cli.shutil, "which", lambda _name: pytest.fail("cursor has no binary to look for"))
    assert _run(tmp_path, v2(root, ref, "cursor"), "--apply") == 0
    assert "Cursor has no command to run" in capsys.readouterr().out


def test_apply_without_the_clients_binary_fails_and_names_it(catalog, tmp_path, home, monkeypatch, capsys) -> None:
    root, ref = catalog
    monkeypatch.setattr(cli.shutil, "which", lambda _name: None)
    assert _run(tmp_path, v2(root, ref, "devin"), "--apply") == 1
    assert "needs the `devin` command" in capsys.readouterr().err
