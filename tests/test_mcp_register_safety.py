"""The MCP registration never follows a link, opens a non-regular file, or touches an entry it did not write."""

from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

from chock.scaffold.mcp_register import McpConfigError, clients, mcp_differences, register, server_entry

ALL = tuple(clients())
CLAUDE = clients()["claude_code"]
CODEX = clients()["codex_cli"]
CURSOR_REL = clients()["cursor"].path
FIFO_PROBE = """
import sys
from chock.scaffold.mcp_register import register, clients
try:
    print(register(sys.argv[1], tuple(clients()), enabled=sys.argv[2] == "on"))
except ValueError as exc:
    print("refused", exc)
"""


def _run(repo, state):
    return subprocess.run(
        [sys.executable, "-c", FIFO_PROBE, str(repo), state],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )


@pytest.mark.parametrize("enabled", [True, False])
def test_symlinked_file_is_refused_or_skipped_and_target_untouched(tmp_path, enabled):
    outside = tmp_path / "outside.json"
    outside.write_text('{"mcpServers": {}}', encoding="utf-8")
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / CLAUDE.path).symlink_to(outside)
    if enabled:
        with pytest.raises(McpConfigError, match="symlink"):
            register(repo, ALL, enabled=True)
    else:
        assert register(repo, ALL, enabled=False) == []
    assert outside.read_text(encoding="utf-8") == '{"mcpServers": {}}'
    assert (repo / CLAUDE.path).is_symlink()


def test_dangling_symlink_is_refused_and_nothing_is_created_through_it(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    target = tmp_path / "created.json"
    (repo / CLAUDE.path).symlink_to(target)
    with pytest.raises(McpConfigError, match="symlink"):
        register(repo, ALL, enabled=True)
    assert not target.exists()


@pytest.mark.parametrize("enabled", [True, False])
def test_symlinked_parent_dir_is_refused_or_skipped(tmp_path, enabled):
    outside = tmp_path / "outside"
    outside.mkdir()
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".cursor").symlink_to(outside)
    if enabled:
        with pytest.raises(McpConfigError, match="symlink"):
            register(repo, ALL, enabled=True)
    else:
        assert register(repo, ALL, enabled=False) == []
    assert list(outside.iterdir()) == []


def test_a_regular_file_in_a_real_dir_is_still_written(tmp_path):
    (tmp_path / ".cursor").mkdir()
    (tmp_path / CURSOR_REL).write_text("{}", encoding="utf-8")
    assert register(tmp_path, ALL, enabled=True)
    assert json.loads((tmp_path / CURSOR_REL).read_text(encoding="utf-8"))["mcpServers"]["chock"]
    assert not [p for p in tmp_path.rglob("*.tmp")]


def test_write_keeps_file_mode(tmp_path):
    path = tmp_path / CLAUDE.path
    path.write_text("{}", encoding="utf-8")
    path.chmod(0o600)
    register(tmp_path, ("claude_code",), enabled=True)
    assert path.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("state", ["on", "off"])
def test_a_fifo_never_hangs(tmp_path, state):
    os.mkfifo(tmp_path / CLAUDE.path)
    run = _run(tmp_path, state)
    assert run.returncode == 0, run.stderr
    assert ("refused" in run.stdout) is (state == "on")


@pytest.mark.parametrize("enabled", [True, False])
def test_a_directory_in_place_of_the_file(tmp_path, enabled):
    (tmp_path / CLAUDE.path).mkdir()
    if enabled:
        with pytest.raises(McpConfigError, match="not a regular file"):
            register(tmp_path, ALL, enabled=True)
    else:
        assert register(tmp_path, ALL, enabled=False) == []
        assert mcp_differences(tmp_path, ALL, enabled=False) == []


def test_non_utf8_never_crashes_when_not_opted_in_and_is_refused_when_opted_in(tmp_path):
    path = tmp_path / CLAUDE.path
    path.write_bytes(b'{"x": "\xff\xfe"}')
    assert register(tmp_path, ALL, enabled=False) == []
    assert mcp_differences(tmp_path, ALL, enabled=False) == []
    with pytest.raises(McpConfigError, match="not valid JSON"):
        register(tmp_path, ALL, enabled=True)
    assert path.read_bytes() == b'{"x": "\xff\xfe"}'


def test_oversize_file_is_refused_unread(tmp_path):
    path = tmp_path / CLAUDE.path
    path.write_text(" " * ((1 << 20) + 1) + "{}", encoding="utf-8")
    assert register(tmp_path, ALL, enabled=False) == []
    with pytest.raises(McpConfigError, match="larger than"):
        register(tmp_path, ALL, enabled=True)


HAND = {
    "command": "git",
    "args": ["-c", "alias.chock-hook=x", "chock-hook", "-m", "chock", "mcp", "--repo", "."],
    "env": {"TOKEN": "s"},
}


def test_a_hand_written_chock_entry_with_env_survives_disable_and_blocks_enable(tmp_path):
    path = tmp_path / CLAUDE.path
    text = json.dumps({"mcpServers": {"chock": HAND}})
    path.write_text(text, encoding="utf-8")
    assert register(tmp_path, ALL, enabled=False) == []
    assert path.read_text(encoding="utf-8") == text
    with pytest.raises(McpConfigError, match="did not write"):
        register(tmp_path, ALL, enabled=True)
    assert path.read_text(encoding="utf-8") == text


def test_an_exact_copy_of_our_entry_is_removed_on_disable(tmp_path):
    path = tmp_path / CLAUDE.path
    path.write_text(json.dumps({"mcpServers": {"chock": server_entry(CLAUDE)}}), encoding="utf-8")
    assert register(tmp_path, ALL, enabled=False)
    assert not path.exists()


def test_forged_toml_markers_around_user_tables_are_never_deleted(tmp_path):
    (tmp_path / ".codex").mkdir()
    path = tmp_path / CODEX.path
    forged = "# chock:mcp:begin -- x\n[mcp_servers.mine]\ncommand = 'node'\n# chock:mcp:end\n"
    path.write_text(forged, encoding="utf-8")
    assert register(tmp_path, ALL, enabled=False) == []
    assert path.read_text(encoding="utf-8") == forged
    with pytest.raises(McpConfigError, match="did not write"):
        register(tmp_path, ALL, enabled=True)


def test_an_edited_toml_block_and_duplicate_blocks_are_left_alone(tmp_path):
    (tmp_path / ".codex").mkdir()
    path = tmp_path / CODEX.path
    register(tmp_path, ("codex_cli",), enabled=True)
    block = path.read_text(encoding="utf-8")
    path.write_text(block + block, encoding="utf-8")
    assert register(tmp_path, ALL, enabled=False) == []
    edited = block.replace('command = "git"', 'command = "git"\nenv = { TOKEN = "s" }')
    path.write_text(edited, encoding="utf-8")
    assert register(tmp_path, ALL, enabled=False) == []
    assert path.read_text(encoding="utf-8") == edited


def test_disable_keeps_key_order_and_non_ascii(tmp_path):
    path = tmp_path / CLAUDE.path
    doc = {
        "b": "é",
        "mcpServers": {"z": {"command": "x"}, "chock": server_entry(CLAUDE), "a": {"command": "y"}},
        "a": 1,
    }
    path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    register(tmp_path, ALL, enabled=False)
    out = json.loads(path.read_text(encoding="utf-8"))
    assert list(out) == ["b", "mcpServers", "a"] and list(out["mcpServers"]) == ["z", "a"]
    assert "é" in path.read_text(encoding="utf-8")


def test_duplicate_keys_are_refused(tmp_path):
    path = tmp_path / CLAUDE.path
    path.write_text('{"mcpServers": {}, "mcpServers": {"x": {}}}', encoding="utf-8")
    with pytest.raises(McpConfigError, match="duplicate keys"):
        register(tmp_path, ALL, enabled=True)


def test_bom_and_crlf_are_kept(tmp_path):
    path = tmp_path / CLAUDE.path
    path.write_bytes('﻿{\r\n  "theme": "dark"\r\n}\r\n'.encode())
    register(tmp_path, ALL, enabled=True)
    raw = path.read_bytes()
    assert raw.startswith("﻿".encode()) and b"\r\n" in raw and b"\n" not in raw.replace(b"\r\n", b"")
    assert json.loads(raw.decode("utf-8-sig"))["mcpServers"]["chock"]
    register(tmp_path, ALL, enabled=False)
    assert json.loads(path.read_bytes().decode("utf-8-sig")) == {"theme": "dark"}


def test_jsonc_comments_are_refused_with_a_clear_message(tmp_path):
    (tmp_path / CLAUDE.path).write_text('{\n // c\n "a": 1}', encoding="utf-8")
    with pytest.raises(McpConfigError, match="comments are not accepted"):
        register(tmp_path, ALL, enabled=True)


def test_a_directory_swapped_for_a_symlink_after_the_check_writes_nothing_outside(tmp_path, monkeypatch):
    from chock.scaffold import mcp_write

    outside = tmp_path / "outside"
    outside.mkdir()
    repo = tmp_path / "repo"
    repo.mkdir()
    real = mcp_write._lstat_checked
    swapped = []

    def swap_after_check(root, rel):
        result = real(root, rel)
        if rel == CURSOR_REL and not swapped:
            swapped.append(1)
            (root / ".cursor").symlink_to(outside)
        return result

    monkeypatch.setattr(mcp_write, "_lstat_checked", swap_after_check)
    with pytest.raises(McpConfigError, match="not a plain directory"):
        register(repo, ALL, enabled=True)
    assert swapped and list(outside.iterdir()) == []


def test_removal_after_a_swap_deletes_nothing_outside(tmp_path, monkeypatch):
    from chock.scaffold import mcp_write

    repo = tmp_path / "repo"
    register(repo, ALL, enabled=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    keep = outside / "mcp.json"
    keep.write_text("{}", encoding="utf-8")
    real = mcp_write._lstat_checked
    swapped = []

    def swap_after_check(root, rel):
        result = real(root, rel)
        if rel == CURSOR_REL and not swapped:
            swapped.append(1)
            (root / ".cursor" / "mcp.json").unlink()
            (root / ".cursor").rmdir()
            (root / ".cursor").symlink_to(outside)
        return result

    monkeypatch.setattr(mcp_write, "_lstat_checked", swap_after_check)
    with pytest.raises(McpConfigError):
        register(repo, ALL, enabled=False)
    assert keep.read_text(encoding="utf-8") == "{}"


def test_an_os_error_at_write_time_is_a_clean_refusal(tmp_path, monkeypatch):
    from chock.scaffold import mcp_register

    def boom(*_a, **_k):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(mcp_register, "write_file", boom)
    with pytest.raises(McpConfigError, match="cannot be written"):
        register(tmp_path, ALL, enabled=True)


def test_the_path_fallback_still_writes(tmp_path, monkeypatch):
    from chock.scaffold import mcp_write

    monkeypatch.setattr(mcp_write, "_fd_safe", lambda: False)
    assert register(tmp_path, ALL, enabled=True)
    assert register(tmp_path, ALL, enabled=False)
    assert not (tmp_path / CLAUDE.path).exists()
