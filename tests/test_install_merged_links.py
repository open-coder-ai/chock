"""`sync` never writes chock's hook entries through a linked agent config."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from chock import vendors
from chock.hooks.in_agent_merged import install_merged
from chock.scaffold.mcp_write import McpConfigError

VENDOR = "claude_code"


def test_a_linked_config_file_is_refused_and_left_alone(tmp_path: Path) -> None:
    outside = tmp_path / "global-settings.json"
    outside.write_text('{"keep": true}', encoding="utf-8")
    repo = tmp_path / "repo"
    config = repo / vendors.config_path(VENDOR)
    config.parent.mkdir(parents=True)
    config.symlink_to(outside)

    with pytest.raises(McpConfigError, match="symlink"):
        install_merged(repo, VENDOR)

    assert outside.read_text(encoding="utf-8") == '{"keep": true}'


def test_a_linked_config_directory_is_refused(tmp_path: Path) -> None:
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    repo = tmp_path / "repo"
    config = repo / vendors.config_path(VENDOR)
    config.parent.parent.mkdir(parents=True, exist_ok=True)
    config.parent.symlink_to(elsewhere, target_is_directory=True)

    with pytest.raises(McpConfigError, match="symlink"):
        install_merged(repo, VENDOR)

    assert list(elsewhere.iterdir()) == []


def test_an_ordinary_config_is_still_merged(tmp_path: Path) -> None:
    config = tmp_path / vendors.config_path(VENDOR)
    config.parent.mkdir(parents=True)
    config.write_text(json.dumps({"keep": True}), encoding="utf-8")

    install_merged(tmp_path, VENDOR)

    assert json.loads(config.read_text(encoding="utf-8"))["keep"] is True
