"""The generic, owned-file and session-start installers write through no link, as `install_merged` does."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from conftest import baseline_policy

from chock import vendors
from chock.compile.compiler import compile_policy
from chock.compile.emitters.in_agent import GENERIC_VENDORS
from chock.compile.surfaces import Surface
from chock.hooks.in_agent_install import agent_hooks_rel, install_hooks, uninstall_hooks
from chock.hooks.sessionstart_install import install_sessionstart_hook
from chock.scaffold.mcp_write import McpConfigError

POLICY = "block-destructive-commands"
JSON_VENDOR = next(v for v in GENERIC_VENDORS if vendors.config_format(v) != "toml")
TOML_VENDOR = next(v for v in GENERIC_VENDORS if vendors.config_format(v) == "toml")
OWNED_VENDOR = "vscode_copilot"


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    compile_policy(
        baseline_policy(POLICY),
        targets=[Surface.PRE_TOOL_USE.value, Surface.AGENT_HOOKS.value],
        output_root=repo / ".chock" / "compiled",
        agents=["claude", "copilot"],
        repo_root=repo,
    )
    return repo


def _rel(vendor: str) -> Path:
    return agent_hooks_rel() if vendor == OWNED_VENDOR else Path(vendors.config_path(vendor))


def _outside(tmp_path: Path) -> Path:
    outside = tmp_path / "outside"
    outside.mkdir()
    return outside


@pytest.mark.parametrize("vendor", [JSON_VENDOR, TOML_VENDOR, OWNED_VENDOR])
def test_a_linked_config_file_is_refused_and_left_alone(tmp_path: Path, vendor: str) -> None:
    repo = _repo(tmp_path)
    target = _outside(tmp_path) / "kept"
    target.write_text("keep", encoding="utf-8")
    link = repo / _rel(vendor)
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(target)

    with pytest.raises(McpConfigError, match="symlink"):
        install_hooks(repo, vendor)

    assert target.read_text(encoding="utf-8") == "keep"


@pytest.mark.parametrize("vendor", [JSON_VENDOR, TOML_VENDOR, OWNED_VENDOR])
def test_a_linked_config_directory_is_refused(tmp_path: Path, vendor: str) -> None:
    repo = _repo(tmp_path)
    elsewhere = _outside(tmp_path)
    link = repo / _rel(vendor).parent
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(elsewhere, target_is_directory=True)

    with pytest.raises(McpConfigError, match="symlink"):
        install_hooks(repo, vendor)

    assert list(elsewhere.iterdir()) == []


@pytest.mark.parametrize("vendor", [JSON_VENDOR, TOML_VENDOR, OWNED_VENDOR])
def test_uninstall_through_a_linked_config_is_refused(tmp_path: Path, vendor: str) -> None:
    repo = _repo(tmp_path)
    target = _outside(tmp_path) / "kept"
    target.write_text("keep", encoding="utf-8")
    link = repo / _rel(vendor)
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(target)

    with pytest.raises(McpConfigError, match="symlink"):
        uninstall_hooks(repo, vendor)

    assert target.exists()
    assert link.is_symlink()


def test_a_linked_session_start_settings_file_is_refused(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    target = _outside(tmp_path) / "kept.json"
    target.write_text("{}", encoding="utf-8")
    link = repo / vendors.config_path("claude_code")
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(target)

    with pytest.raises(McpConfigError, match="symlink"):
        install_sessionstart_hook(repo)

    assert target.read_text(encoding="utf-8") == "{}"


@pytest.mark.parametrize("vendor", [JSON_VENDOR, OWNED_VENDOR])
def test_an_ordinary_repo_is_still_installed(tmp_path: Path, vendor: str) -> None:
    repo = _repo(tmp_path)

    install_hooks(repo, vendor)

    assert json.loads((repo / _rel(vendor)).read_text(encoding="utf-8"))
    assert not (repo / _rel(vendor)).is_symlink()
