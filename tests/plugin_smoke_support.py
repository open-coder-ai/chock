"""Run every hook a built plugin carries the way its client would, and say what each answered."""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

from conftest import bash_executable

#: Every client's plugin-root variable, all pointing at the package, so one hook command fits any format.
ROOT_VARS = ("CLAUDE_PLUGIN_ROOT", "CURSOR_PLUGIN_ROOT", "PLUGIN_ROOT", "DEVIN_PLUGIN_ROOT")
#: Decision words that mean the hook did not simply let the call through.
NOT_ALLOWED = frozenset({"ask", "deny", "block"})
DECISION_KEYS = frozenset({"permissionDecision", "permission", "decision"})
CRASH_MARKERS = ("traceback", "not checked", "internal error", "could not reach a decision", "exited 1 without")
WRITE_TOOLS = ("Write", "apply_patch", "Edit")
BENIGN_COMMAND = "ls -la"


def hook_entries(doc: dict[str, Any]) -> list[tuple[str, str, str]]:
    """(event, matcher, command) for every command in a client's hooks document, whatever its nesting."""
    body = doc.get("hooks", doc)
    found: list[tuple[str, str, str]] = []
    for event, entries in body.items():
        if not isinstance(entries, list):
            continue
        for entry in entries:
            for hook in entry.get("hooks", [entry]):
                if "command" in hook:
                    found.append((event, entry.get("matcher", ".*"), hook["command"]))
    return found


def _payload(client: str, kind: str, repo: Path, command: str, matcher: str) -> str:
    """The stdin one hook receives: a shell command, a file write, or the end of the turn."""
    tool = next((name for name in WRITE_TOOLS if re.fullmatch(matcher, name)), "Write")
    write = {"file_path": str(repo / "notes.txt"), "content": "hello\n"}
    if client == "cursor":
        base = {"conversation_id": "c", "generation_id": "g", "workspace_roots": [str(repo)], "cwd": str(repo)}
        fields = {
            "shell": {"hook_event_name": "beforeShellExecution", "command": command},
            "write": {"hook_event_name": "preToolUse", "tool_name": "Write", "tool_input": write},
            "stop": {"hook_event_name": "stop", "status": "completed", "loop_count": 0},
        }[kind]
        return "﻿" + json.dumps({**base, **fields})
    fields = {
        "shell": {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": command}},
        "write": {"hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": write},
        "stop": {"hook_event_name": "Stop", "stop_hook_active": False},
    }[kind]
    return json.dumps({**fields, "cwd": str(repo)})


def _kind(command: str) -> str:
    if "--stop" in command:
        return "stop"
    return "write" if "--gate" in command else "shell"


def _decisions(value: Any) -> list[str]:
    if isinstance(value, dict):
        own = [str(v).lower() for k, v in value.items() if k in DECISION_KEYS and isinstance(v, str)]
        return own + [d for v in value.values() for d in _decisions(v)]
    return [d for v in value for d in _decisions(v)] if isinstance(value, list) else []


def verdict(proc: subprocess.CompletedProcess) -> str:
    """`allow`, or why the hook did not: `crash`, `ask`, `deny` or `block`."""
    text = (proc.stderr or "").lower()
    out = (proc.stdout or "").lstrip("﻿").strip()
    said = []
    if out:
        try:
            said = [d for d in _decisions(json.loads(out)) if d in NOT_ALLOWED]
        except ValueError:
            said = []
    if proc.returncode not in (0, 2) or any(m in text for m in CRASH_MARKERS):
        return "crash"
    if proc.returncode == 2:
        return "deny"
    return said[0] if said else "allow"


def run_hooks(
    client: str, package: Path, hooks_rel: str, repo: Path, command: str = BENIGN_COMMAND
) -> list[tuple[str, str, str]]:
    """(hook command, kind, verdict) for every hook the package declares, each given `command` or a harmless write."""
    doc = json.loads((package / hooks_rel).read_text(encoding="utf-8"))
    env = {**os.environ, **{name: str(package) for name in ROOT_VARS}, "CHOCK_GATE_LOG": "0"}
    for name in ("CHOCK_AGENT_COMMIT", "CLAUDECODE", "AI_AGENT"):
        env.pop(name, None)
    results = []
    for _event, matcher, hook in hook_entries(doc):
        kind = _kind(hook)
        proc = subprocess.run(
            [bash_executable(), "-c", hook],
            cwd=repo,
            env=env,
            input=_payload(client, kind, repo, command, matcher),
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
            timeout=60,
        )
        results.append((hook, kind, verdict(proc)))
    return results
