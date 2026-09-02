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


@pytest.mark.parametrize("vendor", GENERIC_VENDORS)
def test_install_writes_config_runtime_and_reports(tmp_path: Path, vendor: str) -> None:
    repo = _repo(tmp_path)

    installed = install_hooks(repo, vendor)

    assert installed == [POLICY]
    assert (repo / ".chock" / "bin" / f"{vendor}.py").exists()
    text = json.dumps(_config(repo, vendor))
    assert f".chock/bin/{vendor}.py" in text
    assert sys.executable in text, "the interpreter placeholder must be baked at install"
    assert "@CHOCK_PYTHON@" not in text
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


def test_a_stale_interpreter_is_rebaked_not_reused(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    install_hooks(repo, "devin")
    config_path = repo / vendors.config_path("devin")
    stale = config_path.read_text(encoding="utf-8").replace(sys.executable, "/no/such/python3")
    config_path.write_text(stale, encoding="utf-8")

    install_hooks(repo, "devin")

    text = config_path.read_text(encoding="utf-8")
    assert "/no/such/python3" not in text
    assert sys.executable in text
