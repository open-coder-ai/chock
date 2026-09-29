"""Cases beyond commit and push: gate replay at the agent events, and git-event scripts."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

from chock.eval.fixture import prepare, write_files
from chock.gate.guard_runner import find_interpreter, interpreter_env, is_guard_crash
from chock.validation.checks_script_events import script_path

BLOCK = "block"
ALLOW = "allow"
ERROR = "error"

#: Case `event` -> the runner event it replays at. `stop` reads the turn's end from disk.
AGENT_CASE_EVENTS = {"tool_use": "pre-tool-use", "pre-tool-use": "pre-tool-use", "stop": "stop"}

#: Case `event` -> the `hook.script.on` key naming the script it runs.
SCRIPT_CASE_EVENTS = {"pre-commit": "commit", "pre-push": "push", "commit-msg": "commit-msg"}

_SCRIPT_TIMEOUT_SECONDS = 30
_COMMIT_MSG_FILE = ".git/COMMIT_EDITMSG"


def prepare_agent(repo: Path, spec: dict[str, Any]) -> tuple[dict[str, str], dict[str, str]]:
    """Build HEAD, then return (writes, added) for an agent-event case; nothing is staged.

    `writes` (or `files`) is each file as the agent would leave it. At `stop` the turn's writes
    are already on disk; at tool use they are not, so the file on disk is still HEAD's.
    """
    prepare(repo, {k: v for k, v in spec.items() if k != "files"})
    writes = {str(p): str(t) for p, t in (spec.get("writes") or spec.get("files") or {}).items()}
    if AGENT_CASE_EVENTS[str(spec["event"])] == "stop":
        write_files(repo, writes)
    added = {str(p): str(t) for p, t in (spec.get("added") or {}).items()}
    return writes, added


def _verdict(proc: subprocess.CompletedProcess) -> tuple[str, str]:
    """Exit 0 allows, anything else refuses -- except a crash, which judged nothing."""
    output = (proc.stderr or "") + (proc.stdout or "")
    lines = output.strip().splitlines()
    first = lines[0] if lines else f"script exit {proc.returncode}"
    if proc.returncode == 0:
        return ALLOW, first
    if proc.returncode == 1 and is_guard_crash(output):
        return ERROR, f"script exited 1 without a reason, so nothing was checked: {first}"
    return BLOCK, first


def run_script_event(repo: Path, policy_dir: Path, policy_id: str, spec: dict[str, Any]) -> tuple[str, str]:
    """Stage the case in a throwaway repo and run the policy's script for its event, as the hook would."""
    event = str(spec["event"])
    script = script_path(policy_dir, policy_id, SCRIPT_CASE_EVENTS[event])
    if script is None:
        return ERROR, f"case runs at {event} but the policy ships no script for it"
    interpreter = find_interpreter(script)
    if interpreter is None:
        return ERROR, "no interpreter could resolve the script path"
    if event == "commit-msg" and "message" not in spec:
        return ERROR, "commit-msg case declares no message, so the script would judge nothing"
    prepare(repo, spec)

    argv = [interpreter, str(script)]
    stdin = None
    if event == "commit-msg":
        message = repo / _COMMIT_MSG_FILE
        message.write_text(str(spec.get("message", "")), encoding="utf-8", newline="\n")
        argv.append(str(message))
    elif event == "pre-push":
        stdin = "".join(f"{line}\n" for line in spec.get("stdin") or [])
    try:
        proc = subprocess.run(  # noqa: S603 -- running the policy's own script is the point of this harness
            argv,
            cwd=str(repo),
            input=stdin if stdin is not None else "",
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=_SCRIPT_TIMEOUT_SECONDS,
            env=interpreter_env(interpreter) if interpreter != sys.executable else None,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return ERROR, f"script could not run: {exc}"

    return _verdict(proc)
