"""`chock install --selection`: verify against the pinned catalog, build one merged plugin, swap it in."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
from bundle_fixtures import ADVISORY_ID, GATE_ID, GUARD_ID, MARKER, denies, hook_commands, project, run_command
from install_fixtures import make_catalog, selection, side_commit, write_selection

from chock.install import cli, package

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git required")
PLUGIN = package.settings()["plugin"]
WRITE = {"hook_event_name": "PreToolUse", "tool_name": "Write", "tool_input": {"file_path": "a.txt", "content": MARKER}}
CLEAN = {**WRITE, "tool_input": {"file_path": "a.txt", "content": "fine"}}
RM = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": "rm -rf /"}}


@pytest.fixture
def catalog(tmp_path: Path) -> tuple[Path, str]:
    return make_catalog(tmp_path)


def _run(tmp_path: Path, data: dict, dest: Path, *extra: str, trusted: bool = True) -> int:
    """Run the command; the fixture catalog is a local path, so it is allowed explicitly unless `trusted` is off."""
    path = write_selection(tmp_path / "chock.selection.yaml", data)
    allow = ["--allow-source", data["catalog"]["source"]] if trusted else []
    return cli.main(["--selection", str(path), "--dest", str(dest), *allow, *extra])


def _plugin(dest: Path) -> Path:
    return dest / package.CLIENT / PLUGIN


def test_the_selection_builds_one_plugin_in_a_local_marketplace(catalog, tmp_path: Path, capsys) -> None:
    root, ref = catalog
    dest = tmp_path / "market"
    assert _run(tmp_path, selection(root, ref), dest) == 0
    index = json.loads((dest / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8"))
    assert index["name"] == package.settings()["marketplace"]
    assert [p["name"] for p in index["plugins"]] == [PLUGIN]
    assert index["plugins"][0]["source"] == f"./{package.CLIENT}/{PLUGIN}"
    manifest = json.loads((_plugin(dest) / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    assert manifest["name"] == PLUGIN
    assert "dependencies" not in manifest
    for policy_id in (GUARD_ID, GATE_ID, ADVISORY_ID):
        assert (_plugin(dest) / "skills" / policy_id / "SKILL.md").is_file()
    assert json.loads((dest / package.MARKER).read_text(encoding="utf-8")) == selection(root, ref)
    out = capsys.readouterr().out
    assert f"claude plugin install {PLUGIN}@{package.settings()['marketplace']}" in out
    assert "claude plugin marketplace add" in out


def test_each_member_hook_is_wired_exactly_once_per_event(catalog, tmp_path: Path) -> None:
    root, ref = catalog
    dest = tmp_path / "market"
    assert _run(tmp_path, selection(root, ref), dest) == 0
    events = json.loads((_plugin(dest) / "hooks" / "hooks.json").read_text(encoding="utf-8"))["hooks"]
    for event, entries in events.items():
        commands = hook_commands(entries)
        assert len(commands) == len(set(commands)), f"{event} runs one hook twice"
    commands = hook_commands(events)
    assert sum(f"/scripts/{GUARD_ID}/" in c and "--guard" in c for c in commands) == 1
    assert any(f"/scripts/{GATE_ID}/" in c and "--gate" in c for c in commands)
    assert not any(ADVISORY_ID in c for c in commands)


def test_the_installed_plugin_denies_what_its_members_deny(catalog, tmp_path: Path) -> None:
    root, ref = catalog
    dest = tmp_path / "market"
    assert _run(tmp_path, selection(root, ref), dest) == 0
    commands = hook_commands(json.loads((_plugin(dest) / "hooks" / "hooks.json").read_text(encoding="utf-8")))
    repo = project(tmp_path)

    def blocked(payload: dict) -> bool:
        return any(denies(run_command(c, _plugin(dest), repo, payload)) for c in commands)

    assert blocked(RM)
    assert blocked(WRITE)
    assert not blocked(CLEAN)


def test_each_policy_is_labelled_and_no_aggregate_grade_is_printed(catalog, tmp_path: Path, capsys) -> None:
    root, ref = catalog
    assert _run(tmp_path, selection(root, ref), tmp_path / "market") == 0
    out = capsys.readouterr().out
    assert f"{GUARD_ID}  blocks    refuses a matched shell command" in out
    assert f"{GATE_ID}   blocks    blocks on an agent's file writes" in out
    assert f"{ADVISORY_ID}       advisory  advisory only" in out
    for policy_id in (GUARD_ID, GATE_ID, ADVISORY_ID):
        assert f"{policy_id} stands in for a policy." in out
    assert "weakest" not in out.lower()
    assert f"warning: {ADVISORY_ID} is text only" in out
    assert package.settings()["disclaimer"] in out


def test_the_plugin_manifest_labels_each_member_with_no_aggregate_posture(catalog, tmp_path: Path) -> None:
    root, ref = catalog
    dest = tmp_path / "market"
    assert _run(tmp_path, selection(root, ref), dest) == 0
    manifest = json.loads((_plugin(dest) / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    text = manifest["description"]
    assert f"{GUARD_ID}: refuses a matched shell command before it runs" in text
    assert f"{ADVISORY_ID}: advisory only" in text
    assert "[" not in text
    assert not {"advise", "warn", "ask", "block"} & set(manifest["keywords"])
    index = json.loads((dest / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8"))
    assert index["plugins"][0]["description"] == text


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    [("sha256", "0" * 64, "expected sha256"), ("version", "9.9.9", "names version 9.9.9"), ("id", "no-such", "not in")],
)
def test_a_mismatch_refuses_and_names_the_policy(catalog, tmp_path: Path, capsys, field, value, expected) -> None:
    root, ref = catalog
    data = selection(root, ref)
    data["policies"][1][field] = value
    dest = tmp_path / "market"
    assert _run(tmp_path, data, dest) == 1
    err = capsys.readouterr().err
    assert expected in err
    assert (value if field == "id" else GATE_ID) in err
    assert not dest.exists()


def test_a_commit_the_catalog_lacks_is_refused_with_exit_2(catalog, tmp_path: Path) -> None:
    root, _ref = catalog
    assert _run(tmp_path, selection(root, "1" * 40), tmp_path / "market") == 2


def test_a_rerun_replaces_the_build_and_says_to_reload(catalog, tmp_path: Path, capsys) -> None:
    root, ref = catalog
    dest = tmp_path / "market"
    assert _run(tmp_path, selection(root, ref), dest) == 0
    first = json.loads((_plugin(dest) / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))["version"]
    capsys.readouterr()
    assert _run(tmp_path, selection(root, ref, (GUARD_ID,)), dest) == 0
    manifest = json.loads((_plugin(dest) / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    assert manifest["name"] == PLUGIN
    assert manifest["version"] != first
    assert not (_plugin(dest) / "skills" / GATE_ID).exists()
    assert not (_plugin(dest) / "scripts" / GATE_ID).exists()
    assert "/reload-plugins" in capsys.readouterr().out
    assert sorted(p.name for p in tmp_path.iterdir() if p.name.startswith(".market")) == []


def test_a_failed_rerun_leaves_the_previous_build_untouched(catalog, tmp_path: Path) -> None:
    root, ref = catalog
    dest = tmp_path / "market"
    assert _run(tmp_path, selection(root, ref), dest) == 0
    before = {p.relative_to(dest): p.read_bytes() for p in dest.rglob("*") if p.is_file()}
    bad = selection(root, ref)
    bad["policies"][0]["sha256"] = "0" * 64
    assert _run(tmp_path, bad, dest) == 1
    assert {p.relative_to(dest): p.read_bytes() for p in dest.rglob("*") if p.is_file()} == before


def test_a_directory_chock_did_not_build_is_never_replaced(catalog, tmp_path: Path, capsys) -> None:
    root, ref = catalog
    dest = tmp_path / "mine"
    dest.mkdir()
    (dest / "notes.txt").write_text("keep", encoding="utf-8")
    assert _run(tmp_path, selection(root, ref), dest) == 1
    assert "not a chock install directory" in capsys.readouterr().err
    assert (dest / "notes.txt").read_text(encoding="utf-8") == "keep"


def _stub_claude(tmp_path: Path, monkeypatch) -> Path:
    bin_dir, log = tmp_path / "bin", tmp_path / "claude.log"
    bin_dir.mkdir()
    stub = bin_dir / "claude"
    stub.write_text(f'#!/bin/sh\necho "$*" >> "{log}"\n', encoding="utf-8")
    stub.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    return log


@pytest.mark.skipif(os.name == "nt", reason="the stub is a POSIX shell script")
def test_apply_runs_the_same_two_client_commands_on_every_run(catalog, tmp_path: Path, monkeypatch) -> None:
    root, ref = catalog
    log = _stub_claude(tmp_path, monkeypatch)
    dest = tmp_path / "market"
    marketplace = package.settings()["marketplace"]
    assert _run(tmp_path, selection(root, ref), dest, "--apply") == 0
    assert log.read_text(encoding="utf-8").splitlines() == [
        f"plugin marketplace add {dest.resolve()}",
        f"plugin install {PLUGIN}@{marketplace}",
    ]
    log.unlink()
    assert _run(tmp_path, selection(root, ref, (GUARD_ID,)), dest, "--apply") == 0
    assert log.read_text(encoding="utf-8").splitlines() == [
        f"plugin marketplace add {dest.resolve()}",
        f"plugin install {PLUGIN}@{marketplace}",
    ]


def test_apply_without_the_client_on_path_fails(catalog, tmp_path: Path, monkeypatch, capsys) -> None:
    root, ref = catalog
    monkeypatch.setattr(cli.shutil, "which", lambda _name: None)
    assert _run(tmp_path, selection(root, ref), tmp_path / "market", "--apply") == 1
    assert "needs the `claude` command" in capsys.readouterr().err


@pytest.mark.skipif(os.name == "nt", reason="the stub is a POSIX shell script")
def test_apply_stops_at_the_first_failing_client_command(catalog, tmp_path: Path, monkeypatch, capsys) -> None:
    root, ref = catalog
    log = _stub_claude(tmp_path, monkeypatch)
    (tmp_path / "bin" / "claude").write_text(f'#!/bin/sh\necho "$*" >> "{log}"\nexit 3\n', encoding="utf-8")
    assert _run(tmp_path, selection(root, ref), tmp_path / "market", "--apply") == 3
    assert len(log.read_text(encoding="utf-8").splitlines()) == 1
    assert "exited 3" in capsys.readouterr().err


def test_an_untrusted_source_is_refused_without_the_flag(catalog, tmp_path: Path, capsys) -> None:
    root, ref = catalog
    dest = tmp_path / "market"
    assert _run(tmp_path, selection(root, ref), dest, trusted=False) == 1
    out, err = capsys.readouterr()
    assert out.splitlines()[:2] == [f"Catalog source: {root}", f"Catalog ref:    {ref}"]
    assert "is not trusted" in err
    assert "--allow-source" in err
    assert not dest.exists()


def test_the_default_trusted_source_is_the_official_catalog_only() -> None:
    assert package.settings()["trusted_sources"] == ["https://github.com/open-coder-ai/chock-catalog"]


def test_a_commit_not_on_the_published_branch_is_refused(catalog, tmp_path: Path, capsys) -> None:
    root, _ref = catalog
    sha = side_commit(root)
    dest = tmp_path / "market"
    assert _run(tmp_path, selection(root, sha), dest) == 1
    assert f"commit {sha} is not on {root}'s main branch. Nothing was installed." in capsys.readouterr().err
    assert not dest.exists()


def test_a_commit_behind_the_tip_of_main_is_accepted(catalog, tmp_path: Path) -> None:
    root, ref = catalog
    (root / "LATER.md").write_text("later\n", encoding="utf-8")
    for args in (("add", "-A"), ("-c", "user.email=t@example.com", "-c", "user.name=t", "commit", "-qm", "later")):
        subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)
    assert _run(tmp_path, selection(root, ref), tmp_path / "market") == 0
