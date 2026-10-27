"""goose, grok, antigravity, openhands, kimi and droid payloads, for suites over every plugin client.

Shapes follow agentseam's vendor fields (and each vendor's hooks page): goose names the event under
`event` and the folder under `working_dir`; grok sends both event keys; antigravity names no event,
nests the call under `toolCall` and lists `workspacePaths`; openhands names the event under
`event_type` and the folder under `working_dir`; kimi marks itself by `client_type`; droid sends
Claude's keys with its own `permission_mode` values.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from chock.plugin import gate_package, hook_dir
from chock.plugin.bundle_build import CLIENTS


def pre_tool(client: str, repo: Path, tool: str, tool_input: dict[str, Any]) -> dict[str, Any] | None:
    """`tool` ("Bash" or "Write") called in `client`'s own shape; None for a client not covered here."""
    if client in _ENVELOPES:
        return _marked_pre_tool(client, repo, tool == "Write", tool_input)
    return _named_pre_tool(client, repo, tool, tool_input)


def _named_pre_tool(client: str, repo: Path, tool: str, tool_input: dict[str, Any]) -> dict[str, Any] | None:
    write = tool == "Write"
    if client == "goose":
        args = {"path": tool_input["file_path"], "content": tool_input["content"]} if write else tool_input
        body = {"event": "PreToolUse", "session_id": "s", "tool_call_id": "call-1", "working_dir": str(repo)}
        return {**body, "tool_name": "write" if write else "shell", "tool_input": args}
    if client == "grok":
        body = {"hook_event_name": "PreToolUse", "hookEventName": "pre_tool_use", "sessionId": "s", "cwd": str(repo)}
        return {**body, "toolName": tool, "toolInput": tool_input}
    if client == "antigravity":
        args = (
            {"TargetFile": tool_input["file_path"], "CodeContent": tool_input["content"]}
            if write
            else {"CommandLine": tool_input["command"], "Cwd": str(repo)}
        )
        call = {"name": "write_to_file" if write else "run_command", "args": args}
        return {"toolCall": call, "stepIdx": 1, "conversationId": "c", "workspacePaths": [str(repo)]}
    if client == "openhands":
        args = (
            {"command": "create", "path": tool_input["file_path"], "file_text": tool_input["content"]}
            if write
            else tool_input
        )
        body = {"event_type": "PreToolUse", "session_id": "s", "working_dir": str(repo)}
        return {**body, "tool_name": "file_editor" if write else "terminal", "tool_input": args}
    return None


#: The envelope keys kimi and droid send on every event (agentseam's golden payloads at bebbfa6).
_ENVELOPES = {
    "kimi": {"session_id": "s", "session_title": "t", "client_type": "kimi_code_cli"},
    "droid": {"session_id": "s", "permission_mode": "auto-medium", "transcript_path": "/x/.factory/projects/x/s.jsonl"},
}


def _marked_pre_tool(client: str, repo: Path, write: bool, tool_input: dict[str, Any]) -> dict[str, Any]:
    """kimi and droid, which mark themselves by an envelope value: kimi's write names its file `path`."""
    names = {"kimi": ("WriteFile", "Shell"), "droid": ("Create", "Execute")}[client]
    args = dict(tool_input)
    if write and client == "kimi":
        args = {"path": tool_input["file_path"], "content": tool_input["content"]}
    body = {**_ENVELOPES[client], "hook_event_name": "PreToolUse", "cwd": str(repo)}
    return {**body, "tool_name": names[0] if write else names[1], "tool_input": args}


def stop(client: str, repo: Path) -> dict[str, Any] | None:
    """A clean turn end in `client`'s own shape; None for a client not covered here."""
    if client in _ENVELOPES:
        extra = {"stop_hook_active": False} if client == "droid" else {}
        return {**_ENVELOPES[client], "hook_event_name": "Stop", "cwd": str(repo), **extra}
    return _named_stop(client, repo)


def _named_stop(client: str, repo: Path) -> dict[str, Any] | None:
    if client == "goose":
        return {"event": "Stop", "session_id": "s", "last_assistant_message": "done"}
    if client == "grok":
        return {"hook_event_name": "Stop", "hookEventName": "stop", "sessionId": "s", "cwd": str(repo)}
    if client == "antigravity":
        body = {"executionNum": 1, "terminationReason": "model_stop", "error": "", "fullyIdle": True}
        return {**body, "conversationId": "c", "workspacePaths": [str(repo)]}
    if client == "openhands":
        return {"event_type": "Stop", "session_id": "s", "working_dir": str(repo)}
    return None


def has_stop(client: str) -> bool:
    """Whether `client`'s package runs anything at the turn's end (grok's records no blocking Stop)."""
    return gate_package.gate_reach(CLIENTS[client].agent)[1]


def rootless(client: str) -> bool:
    """Whether `client`'s hooks name the plugin folder by absolute path, the vendor documenting no root variable."""
    own = CLIENTS[client].own_layout
    return own is not None and hook_dir.layout(own)["plugin_root"] is None


#: Each runtime's own pre-tool deny, as its client reads it.
PRE_TOOL_DENIES = {
    "goose": lambda p: p.returncode == 0 and _decision(p) == "block",
    "antigravity": lambda p: p.returncode == 0 and _decision(p) == "deny",
    "gemini_cli": lambda p: p.returncode == 0 and _decision(p) == "deny",
    "openhands": lambda p: p.returncode == 0 and _decision(p) == "deny",
    # Kimi and Droid answer PreToolUse in G2: a deny under hookSpecificOutput (agentseam gates.PreToolUse.grammar).
    "kimi_code": lambda p: p.returncode == 0 and _nested(p) == "deny",
    "factory_droid": lambda p: p.returncode == 0 and _nested(p) == "deny",
}


def _nested(proc: Any) -> Any:
    try:
        body = json.loads(proc.stdout or "null")
    except ValueError:
        return None
    return (body.get("hookSpecificOutput") or {}).get("permissionDecision") if isinstance(body, dict) else None


def _decision(proc: Any) -> Any:
    try:
        body = json.loads(proc.stdout or "null")
    except ValueError:
        return None
    return body.get("decision") if isinstance(body, dict) else None


def bash_json(client: str, repo: Path, command: str) -> str | None:
    native = pre_tool(client, repo, "Bash", {"command": command})
    return None if native is None else json.dumps(native)


def write_resolved(folder: Path, files: dict[Path, str]) -> Path:
    """Write a package the way chock does, its root resolved to `folder` where the client names it by path."""
    for rel, content in hook_dir.resolve_root(files, folder).items():
        (folder / rel).parent.mkdir(parents=True, exist_ok=True)
        (folder / rel).write_text(content, encoding="utf-8")
    return folder


def skip_rootless(client: str) -> None:
    if rootless(client):
        pytest.skip(f"{client} names its folder by path: test_plugin_install_targets moves the folder instead")


def in_session(payload: dict[str, Any], session: str) -> dict[str, Any]:
    """`payload` as the client's session `session` sends it: every session or conversation key it has, else `session_id`."""
    keys = [k for k in ("session_id", "sessionId", "conversation_id", "conversationId") if k in payload]
    return {**payload, **dict.fromkeys(keys or ["session_id"], session)}
