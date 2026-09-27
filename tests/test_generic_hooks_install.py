"""The generic in-agent installer: one merge policy over every derived vendor's config shape."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from conftest import baseline_policy

from chock import vendors
from chock.compile.compiler import compile_policy
from chock.compile.emitters.in_agent import GENERIC_VENDORS
from chock.compile.surfaces import Surface
from chock.hooks.in_agent_install import install_hooks, installed_policy_ids
from chock.hooks.launch import LAUNCHER_REL, hook_command

POLICY = "block-destructive-commands"


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "r"
    repo.mkdir()
    compile_policy(
        baseline_policy(POLICY),
        targets=[Surface.PRE_TOOL_USE.value],
        output_root=repo / ".chock" / "compiled",
        agents=["claude"],
        repo_root=repo,
    )
    return repo


def _config(repo: Path, vendor: str) -> dict:
    return json.loads((repo / vendors.config_path(vendor)).read_text(encoding="utf-8"))


def _commands(node) -> list[str]:
    """Every `command` string in a vendor config, whatever shape the vendor nests them in."""
    if isinstance(node, dict):
        found = [v for k, v in node.items() if k == "command" and isinstance(v, str)]
        return found + [c for v in node.values() for c in _commands(v)]
    if isinstance(node, list):
        return [c for v in node for c in _commands(v)]
    return []


def _replace_in_commands(node, old: str, new: str) -> None:
    """Rewrite `command` strings in place, so the edit survives JSON escaping of the path."""
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "command" and isinstance(value, str):
                node[key] = value.replace(old, new)
            else:
                _replace_in_commands(value, old, new)
    elif isinstance(node, list):
        for value in node:
            _replace_in_commands(value, old, new)


@pytest.mark.parametrize("vendor", GENERIC_VENDORS)
def test_install_writes_config_runtime_and_reports(tmp_path: Path, vendor: str) -> None:
    repo = _repo(tmp_path)

    installed = install_hooks(repo, vendor)

    assert installed == [POLICY]
    assert (repo / ".chock" / "bin" / f"{vendor}.py").exists()
    commands = _commands(_config(repo, vendor))
    assert any(f".chock/bin/{vendor}.py" in c for c in commands)
    compiled = repo / ".chock" / "compiled" / POLICY / "pre-tool-use" / f"{vendor}-hooks.json"
    assert commands == _commands(json.loads(compiled.read_text(encoding="utf-8"))), "installed == compiled"
    assert (repo / LAUNCHER_REL).is_file()
    # Compared on the parsed strings, not the JSON text: a Windows interpreter path is
    # backslash-escaped on disk and would never match its own `sys.executable`.
    assert not any(sys.executable in c for c in commands), "no interpreter path may be committed"
    assert not any("@CHOCK_PYTHON@" in c or "${" in c for c in commands)
    assert installed_policy_ids(repo, vendor) == {POLICY}


@pytest.mark.parametrize("vendor", GENERIC_VENDORS)
def test_install_is_idempotent(tmp_path: Path, vendor: str) -> None:
    repo = _repo(tmp_path)
    install_hooks(repo, vendor)
    first = (repo / vendors.config_path(vendor)).read_bytes()

    install_hooks(repo, vendor)

    assert (repo / vendors.config_path(vendor)).read_bytes() == first


@pytest.mark.parametrize("vendor", GENERIC_VENDORS)
def test_removal_deletes_only_what_chock_owns(tmp_path: Path, vendor: str) -> None:
    """No fragments left: our entries and runtime go; a config file that held only ours goes too."""
    import shutil

    repo = _repo(tmp_path)
    install_hooks(repo, vendor)
    shutil.rmtree(repo / ".chock" / "compiled")

    assert install_hooks(repo, vendor) == []

    assert not (repo / vendors.config_path(vendor)).exists()
    assert not (repo / ".chock" / "bin" / f"{vendor}.py").exists()
    assert installed_policy_ids(repo, vendor) == set()


def test_foreign_settings_and_entries_survive_install_and_removal(tmp_path: Path) -> None:
    """gemini's config is a shared settings file: the adopter's keys and hooks are not ours to move."""
    import shutil

    repo = _repo(tmp_path)
    config_path = repo / vendors.config_path("gemini_cli")
    config_path.parent.mkdir(parents=True)
    theirs_entry = {"hooks": [{"type": "command", "command": "./scripts/audit.sh"}]}
    config_path.write_text(json.dumps({"theme": "dark", "hooks": {"BeforeTool": [theirs_entry]}}), encoding="utf-8")

    install_hooks(repo, "gemini_cli")
    settings = _config(repo, "gemini_cli")
    assert settings["theme"] == "dark"
    assert settings["hooks"]["BeforeTool"][0] == theirs_entry, "the adopter's entry stays first"
    assert len(settings["hooks"]["BeforeTool"]) == 2

    shutil.rmtree(repo / ".chock" / "compiled")
    install_hooks(repo, "gemini_cli")
    settings = _config(repo, "gemini_cli")
    assert settings == {"theme": "dark", "hooks": {"BeforeTool": [theirs_entry]}}


def test_windsurf_wires_both_recorded_pre_tool_events(tmp_path: Path) -> None:
    """The also_wires fact reaches the installed file through the rendering, not a chock table."""
    repo = _repo(tmp_path)
    install_hooks(repo, "windsurf")
    hooks = _config(repo, "windsurf")["hooks"]
    assert set(hooks) == {"pre_run_command", "pre_mcp_tool_use"}


def test_an_old_baked_entry_is_replaced_by_the_launcher_form(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    install_hooks(repo, "devin")
    config_path = repo / vendors.config_path("devin")
    current = config_path.read_bytes()
    old = json.loads(current)
    launcher = hook_command(".chock/bin/devin.py")
    _replace_in_commands(old, launcher, '"/no/such/python3" ".chock/bin/devin.py"')
    assert "/no/such/python3" in json.dumps(old)
    config_path.write_text(json.dumps(old, indent=2), encoding="utf-8")
    assert installed_policy_ids(repo, "devin") == set(), "an old-form entry is not current"

    install_hooks(repo, "devin")

    assert config_path.read_bytes() == current, "the old entry is ours: replaced, not kept beside the new one"


def test_a_generic_vendor_with_a_write_vocabulary_gets_its_write_gate_installed(tmp_path: Path) -> None:
    """gemini_cli's write fragment was compiled as a bare entry and never merged: no write gate."""
    vendor = "gemini_cli"
    assert vendors.write_matcher(vendor), "the premise: gemini_cli records write tools"
    repo = tmp_path / "r"
    repo.mkdir()
    compile_policy(
        baseline_policy("pin-github-actions"),
        targets=[Surface.PRE_TOOL_USE.value],
        output_root=repo / ".chock" / "compiled",
        agents=["gemini"],
        repo_root=repo,
    )
    install_hooks(repo, vendor)

    entries = _config(repo, vendor)["hooks"][vendors.pre_tool_event(vendor)]
    write = [e for e in entries if e.get("matcher") == vendors.write_matcher(vendor)]
    assert write, "the write gate is wired under the vendor's own pre-tool event"
    assert write[0]["hooks"][0]["command"] == hook_command(
        f".chock/bin/{vendor}.py", "--gate", ".chock/compiled/pin-github-actions/pre-tool-use/gate.json"
    )
    assert "pin-github-actions" in installed_policy_ids(repo, vendor)
