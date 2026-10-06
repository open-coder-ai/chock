"""A merged bundle per client, its hook commands, and payloads in each client's own shape."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from bundle_fixtures import ALL_ROOTS, BUNDLE_ID, MARKER, bundle, hook_commands, make_members, project, write
from conftest import run_hook_command

from chock.plugin.bundle_build import CLIENTS, merged_files

MERGED_CLIENTS = sorted(CLIENTS)
TOGGLE = ".chock/guardrails.json"


def build(tmp_path: Path, client: str) -> tuple[Path, Path, list[str]]:
    """(plugin folder, project repo, every hook command) for a merged demo bundle in `client`'s format."""
    members = make_members(tmp_path)
    out = write(tmp_path / "dist" / client / BUNDLE_ID, merged_files(client, bundle(members), members, tmp_path))
    hooks = next(p for p in out.rglob("hooks.json"))
    return out, project(tmp_path), hook_commands(json.loads(hooks.read_text(encoding="utf-8")))


def shell(client: str, repo: Path, command: str) -> dict[str, Any]:
    if client == "cursor":
        return {
            "conversation_id": "c",
            "generation_id": "g",
            "workspace_roots": [str(repo)],
            "cwd": str(repo),
            "hook_event_name": "beforeShellExecution",
            "command": command,
        }
    return {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(repo)}


def write_call(client: str, repo: Path, path: str, content: str = MARKER) -> dict[str, Any]:
    tool_input = {"file_path": path, "content": content}
    if client == "cursor":
        return {
            "conversation_id": "c",
            "generation_id": "g",
            "workspace_roots": [str(repo)],
            "cwd": str(repo),
            "hook_event_name": "preToolUse",
            "tool_name": "Write",
            "tool_input": tool_input,
        }
    return {"hook_event_name": "PreToolUse", "tool_name": "Write", "tool_input": tool_input, "cwd": str(repo)}


def refused(proc: Any) -> bool:
    """Whether a hook did not let the call through, in any client's dialect."""
    out = proc.stdout.lower()
    return proc.returncode == 2 or any(word in out for word in ('"deny"', '"block"', '"ask"'))


def outcomes(commands: list[str], plugin: Path, repo: Path, payload: dict, home: Path) -> list[Any]:
    """Each hook's process, run the way its client runs it, with HOME at `home`."""
    env = {**os.environ, **dict.fromkeys(ALL_ROOTS, plugin.as_posix()), "HOME": str(home), "USERPROFILE": str(home)}
    return [run_hook_command(c, repo, json.dumps(payload), env=env) for c in commands]


def any_refused(commands: list[str], plugin: Path, repo: Path, payload: dict, home: Path) -> bool:
    return any(refused(p) for p in outcomes(commands, plugin, repo, payload, home))


def set_toggles(where: Path, bundles: dict[str, dict[str, str]] | str) -> Path:
    """Write a toggle file at `where/.chock/guardrails.json`; a string is written as is."""
    path = where / TOGGLE
    path.parent.mkdir(parents=True, exist_ok=True)
    text = bundles if isinstance(bundles, str) else json.dumps({"version": 1, "bundles": bundles})
    path.write_text(text, encoding="utf-8")
    return path
