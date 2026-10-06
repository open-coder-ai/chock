"""Every client's merged bundle refuses exactly what its members refuse alone."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from bundle_fixtures import ALL_ROOTS, BUNDLE_ID, MARKER, bundle, hook_commands, make_members, project, write
from conftest import run_hook_command

from chock.plugin.bundle_build import CLIENTS, merged_files

MERGED_CLIENTS = sorted(CLIENTS)


def _payload(client: str, repo: Path, tool: str, **tool_input: str) -> str:
    """The pre-tool payload each client sends: its own envelope, event spelling and markers."""
    if tool == "Write":
        tool_input = {**tool_input, "file_path": str(repo / tool_input["file_path"])}
    body: dict = {"hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": tool_input, "cwd": str(repo)}
    if client == "cursor":
        envelope = {"conversation_id": "c", "generation_id": "g", "cursor_version": "3.21.18"}
        body = {**envelope, **body, "hook_event_name": "preToolUse", "workspace_roots": [str(repo)]}
        return "\ufeff" + json.dumps(body)
    if client == "devin":
        body["prompt_id"] = "p"
    if client == "copilot":
        body = {**body, "toolName": tool.lower(), "toolArgs": json.dumps(tool_input)}
    return json.dumps(body)


def _refuses(proc: object) -> bool:
    """A refusal in any client's grammar: exit 2, or a deny (Claude, Codex, Cursor, Copilot) or block (Devin)."""
    out = proc.stdout.lower()
    return proc.returncode == 2 or (proc.returncode == 0 and ('"deny"' in out or '"block"' in out))


def _outcomes(package: Path, repo: Path, payload: str) -> bool:
    hooks = next(package.rglob("hooks.json"))
    commands = hook_commands(json.loads(hooks.read_text(encoding="utf-8")))
    env = {**os.environ, **dict.fromkeys(ALL_ROOTS, package.as_posix())}
    return any(_refuses(run_hook_command(c, repo, payload, env=env)) for c in commands)


@pytest.mark.parametrize("client", MERGED_CLIENTS)
def test_a_merged_bundle_refuses_exactly_what_its_members_refuse_alone(tmp_path: Path, client: str) -> None:
    members = make_members(tmp_path)
    dist = tmp_path / "dist" / client
    alone = [write(dist / m.id, CLIENTS[client].files(m.policy_dir, m.manifest, tmp_path)) for m in members]
    merged = write(dist / BUNDLE_ID, merged_files(client, bundle(members), members, tmp_path))
    repo = project(tmp_path)
    cases = {
        "forbidden write": (_payload(client, repo, "Write", file_path="App.java", content=MARKER), True),
        "rm -rf": (_payload(client, repo, "Bash", command="rm -rf /"), True),
        "clean write": (_payload(client, repo, "Write", file_path="App.java", content="class App {}"), False),
        "ls": (_payload(client, repo, "Bash", command="ls"), False),
    }
    for case, (payload, refused) in cases.items():
        by_members = any(_outcomes(package, repo, payload) for package in alone)
        assert by_members == refused, (client, case, "members alone")
        assert _outcomes(merged, repo, payload) == by_members, (client, case, "bundle")
