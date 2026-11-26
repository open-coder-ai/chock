"""Run one hook command as its client does: the shell, the probe's own session and the answer."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from chock.doctor.targets import Target
from chock.gate.guard_runner import bash_candidates
from chock.gate.runner.journal import LOG_LEVEL_ENV, LOG_OFF
from chock.plugin import hook_dir, store
from chock.plugin.clients import CLIENTS

#: Seconds one hook command may take; a client's own timeouts are of this order.
TIMEOUT = 60
#: The probe logs nothing, so the decision log never holds a refusal no agent asked for.
QUIET = {LOG_LEVEL_ENV: LOG_OFF}
#: The per-shell keys a hook entry may carry in place of `command` (Copilot's `bash` and `powershell`).
BASH, POWERSHELL = "bash", "powershell"
#: The probe's own session: its calls never join a real session's log, and that file is removed afterwards.
PROBE_SESSION = "chock-doctor-live"
_SESSION_KEYS = ("session_id", "sessionId", "conversation_id", "conversationId", "trajectory_id")


def _argv(agent: str, key: str, command: str) -> list[str] | str:
    """The shell the client runs a hook in on this OS: sh on POSIX; on Windows PowerShell for a `powershell` entry,
    cmd.exe where the store says so, else Git Bash."""
    if os.name != "nt":
        return [shutil.which("sh") or "sh", "-c", command]
    if key == POWERSHELL:
        return [shutil.which("powershell") or "powershell", "-NoProfile", "-Command", command]
    cmd = any(c.agent == agent and store.windows_hook_command(f) == hook_dir.QUOTE_FREE for f, c in CLIENTS.items())
    bash = [] if cmd else bash_candidates()
    return [bash[0], "-c", command] if bash else command


def own_session(sent: dict[str, Any]) -> dict[str, Any]:
    named = [key for key in _SESSION_KEYS if key in sent] or [_SESSION_KEYS[0]]
    return {**sent, **dict.fromkeys(named, PROBE_SESSION)}


def call(target: Target, repo: Path, entry: tuple[str, str], sent: dict[str, Any]) -> subprocess.CompletedProcess | str:
    """One hook command's answer to the payload `sent`, or why it gave none."""
    argv = _argv(target.agent, *entry)
    try:
        return subprocess.run(  # noqa: S603 -- a hook command this engine rendered, byte-equal, as the client runs it
            argv,
            shell=isinstance(argv, str),
            cwd=repo,
            env={**os.environ, **QUIET},
            input=json.dumps(sent),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=TIMEOUT,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"{type(exc).__name__}: {exc}"


def said(done: subprocess.CompletedProcess | str) -> str:
    if isinstance(done, str):
        return done
    text = (done.stderr.strip() or done.stdout.strip()).splitlines()
    return f"exit {done.returncode}" + (f": {text[0][:160]}" if text else "")
