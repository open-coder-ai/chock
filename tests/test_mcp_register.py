"""`chock sync` registers `chock mcp` in each wired client's project MCP config, opt-in and merge-only."""

from __future__ import annotations

import json
import subprocess
import sys
import tomllib

import pytest

from chock.config import guidance_mcp_from_text
from chock.hooks.launch import record_interpreter
from chock.scaffold.init import cmd_init
from chock.scaffold.mcp_register import McpConfigError, clients, mcp_differences, register
from chock.toggles import recompile_main

ALL = tuple(clients())
JSON_CLIENTS = [v for v, c in clients().items() if c.format == "json"]
OTHER = {"command": "node", "args": ["other.js"]}
CLAUDE_FILE = clients()["claude_code"].path


def _read(repo, client):
    text = (repo / client.path).read_text(encoding="utf-8")
    return tomllib.loads(text) if client.format == "toml" else json.loads(text)


def _ours(repo, vendor):
    c = clients()[vendor]
    return _read(repo, c)[c.key]["chock"]


def _snapshot(root):
    return {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}


@pytest.mark.parametrize("vendor", ALL)
def test_enable_creates_entry_and_disable_removes_the_file(tmp_path, vendor):
    c = clients()[vendor]
    assert register(tmp_path, ALL, enabled=True)
    entry = _ours(tmp_path, vendor)
    assert entry["command"] == "git" and entry["args"][-5:] == ["-m", "chock", "mcp", "--repo", "."]
    assert register(tmp_path, ALL, enabled=False)
    assert not (tmp_path / c.path).exists()


def test_enable_is_idempotent(tmp_path):
    register(tmp_path, ALL, enabled=True)
    before = _snapshot(tmp_path)
    assert register(tmp_path, ALL, enabled=True) == []
    assert mcp_differences(tmp_path, ALL, enabled=True) == []
    assert before == _snapshot(tmp_path)


@pytest.mark.parametrize("vendor", JSON_CLIENTS)
def test_other_servers_and_keys_survive_both_directions(tmp_path, vendor):
    c = clients()[vendor]
    path = tmp_path / c.path
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = {"theme": "dark", c.key: {"other": OTHER}}
    path.write_text(json.dumps(doc), encoding="utf-8")
    register(tmp_path, ALL, enabled=True)
    merged = json.loads(path.read_text(encoding="utf-8"))
    assert merged["theme"] == "dark" and merged[c.key]["other"] == OTHER and "chock" in merged[c.key]
    register(tmp_path, ALL, enabled=False)
    assert json.loads(path.read_text(encoding="utf-8")) == doc


def test_vscode_uses_servers_key_with_stdio_type(tmp_path):
    register(tmp_path, ("vscode_copilot",), enabled=True)
    doc = json.loads((tmp_path / ".vscode/mcp.json").read_text(encoding="utf-8"))
    assert "mcpServers" not in doc and doc["servers"]["chock"]["type"] == "stdio"


def test_codex_toml_keeps_comments_and_other_tables(tmp_path):
    path = tmp_path / ".codex" / "config.toml"
    path.parent.mkdir()
    original = '# mine\nmodel = "x"\n\n[mcp_servers.other]\ncommand = "node"\n'
    path.write_text(original, encoding="utf-8")
    register(tmp_path, ALL, enabled=True)
    text = path.read_text(encoding="utf-8")
    servers = tomllib.loads(text)["mcp_servers"]
    assert text.startswith(original) and servers["other"] == {"command": "node"} and "chock" in servers
    register(tmp_path, ALL, enabled=False)
    assert path.read_text(encoding="utf-8") == original


@pytest.mark.parametrize("vendor", ALL)
def test_malformed_config_is_refused_and_untouched(tmp_path, vendor):
    path = tmp_path / clients()[vendor].path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{ not valid ] //", encoding="utf-8")
    with pytest.raises(McpConfigError, match="will not overwrite"):
        register(tmp_path, ALL, enabled=True)
    assert any(d.startswith("unreadable") for d in mcp_differences(tmp_path, ALL, enabled=True))
    assert path.read_text(encoding="utf-8") == "{ not valid ] //"


def test_refusal_writes_nothing_anywhere(tmp_path):
    (tmp_path / ".cursor").mkdir()
    (tmp_path / ".cursor/mcp.json").write_text("nope", encoding="utf-8")
    with pytest.raises(McpConfigError):
        register(tmp_path, ALL, enabled=True)
    assert not (tmp_path / CLAUDE_FILE).exists() and not (tmp_path / ".chock").exists()


def test_disable_leaves_a_malformed_file_with_none_of_ours_alone(tmp_path):
    (tmp_path / CLAUDE_FILE).write_text("{ broken", encoding="utf-8")
    assert register(tmp_path, ALL, enabled=False) == []


@pytest.mark.parametrize("vendor", ALL)
def test_a_foreign_chock_server_is_not_clobbered(tmp_path, vendor):
    c = clients()[vendor]
    path = tmp_path / c.path
    path.parent.mkdir(parents=True, exist_ok=True)
    if c.format == "toml":
        path.write_text('[mcp_servers.chock]\ncommand = "mine"\n', encoding="utf-8")
    else:
        path.write_text(json.dumps({c.key: {"chock": {"command": "mine"}}}), encoding="utf-8")
    with pytest.raises(McpConfigError, match="did not write"):
        register(tmp_path, ALL, enabled=True)
    assert register(tmp_path, ALL, enabled=False) == []
    assert "mine" in path.read_text(encoding="utf-8")


def test_only_wired_clients_are_written_but_removal_covers_every_client(tmp_path):
    register(tmp_path, ("claude_code",), enabled=True)
    assert (tmp_path / CLAUDE_FILE).exists() and not (tmp_path / ".cursor").exists()
    register(tmp_path, ("cursor",), enabled=True)
    register(tmp_path, ("cursor",), enabled=False)
    assert not (tmp_path / CLAUDE_FILE).exists() and not (tmp_path / ".cursor/mcp.json").exists()


def test_committed_output_names_no_home_or_absolute_interpreter(tmp_path):
    register(tmp_path, ALL, enabled=True)
    for p in tmp_path.rglob("*"):
        if p.is_file():
            text = p.read_text(encoding="utf-8")
            assert "/home" not in text and sys.executable not in text and str(tmp_path) not in text
    assert ".chock/bin/launch.sh" in (tmp_path / CLAUDE_FILE).read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("text", "want"),
    [
        ("guidance_mcp: true\n", True),
        ("rollout: warn\nguidance_mcp: 'true'  # yes\n", True),
        ("guidance_mcp: false\n", False),
        ("guidance_mcp: True\n", False),
        ("guidance_mcp: TRUE\n", False),
        ("guidance_mcp: yes\n", False),
        ("guidance_mcp: true\nguidance_mcp: true\n", False),
        ("  guidance_mcp: true\n", False),
        ("", False),
    ],
)
def test_opt_in_reader(text, want):
    assert guidance_mcp_from_text(text) is want


def _sync_repo(tmp_path, *, enabled, agents="claude,cursor,gemini,codex,vscode"):
    repo = tmp_path / "repo"
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    cmd_init([str(repo), "--skip-hooks", "--agents", agents])
    if enabled:
        with (repo / ".chock" / "config.yaml").open("a", encoding="utf-8") as f:
            f.write("\nguidance_mcp: true\n")
    return repo


def test_sync_registers_then_check_reports_drift_then_disable_removes(tmp_path, capsys):
    repo = _sync_repo(tmp_path, enabled=True)
    assert recompile_main(["--repo", str(repo), "--check"]) == 1
    assert CLAUDE_FILE in capsys.readouterr().out
    assert recompile_main(["--repo", str(repo)]) == 0
    assert f"Registered the chock MCP server in {CLAUDE_FILE}" in capsys.readouterr().out
    assert recompile_main(["--repo", str(repo), "--check"]) == 0
    cfg = repo / ".chock" / "config.yaml"
    cfg.write_text(cfg.read_text(encoding="utf-8").replace("guidance_mcp: true", "guidance_mcp: false"), "utf-8")
    assert recompile_main(["--repo", str(repo), "--check"]) == 1
    assert recompile_main(["--repo", str(repo)]) == 0
    assert not (repo / CLAUDE_FILE).exists() and not (repo / ".cursor/mcp.json").exists()
    assert recompile_main(["--repo", str(repo), "--check"]) == 0


def test_sync_without_opt_in_writes_no_mcp_config(tmp_path):
    repo = _sync_repo(tmp_path, enabled=False)
    assert recompile_main(["--repo", str(repo)]) == 0
    assert not (repo / CLAUDE_FILE).exists() and not (repo / ".vscode").exists()


def test_sync_refuses_malformed_config_and_exits_nonzero(tmp_path, capsys):
    repo = _sync_repo(tmp_path, enabled=True)
    (repo / CLAUDE_FILE).write_text("{oops", encoding="utf-8")
    assert recompile_main(["--repo", str(repo)]) == 1
    assert "will not overwrite" in capsys.readouterr().err
    assert (repo / CLAUDE_FILE).read_text(encoding="utf-8") == "{oops"


def test_the_registered_command_starts_the_server(tmp_path):
    """The committed argv, run from the repo root with this interpreter recorded, answers `initialize`."""
    repo = _sync_repo(tmp_path, enabled=True, agents="claude")
    assert recompile_main(["--repo", str(repo)]) == 0
    assert record_interpreter(repo)
    entry = json.loads((repo / CLAUDE_FILE).read_text(encoding="utf-8"))["mcpServers"]["chock"]
    request = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}}
    run = subprocess.run(
        [entry["command"], *entry["args"]],
        cwd=repo,
        input=json.dumps(request) + "\n",
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert run.stdout.strip(), (run.returncode, run.stderr)
    assert json.loads(run.stdout.splitlines()[0])["id"] == 1
