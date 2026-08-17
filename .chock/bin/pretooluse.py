#!/usr/bin/env python3
"""Chock PreToolUse adapter — SELF-CONTAINED, STDLIB ONLY.

Copied verbatim to <repo>/.chock/bin/pretooluse.py by `chock compile`.
MUST NOT import any third-party package or anything from `chock`.

Claude Code delivers a tool invocation as JSON on **stdin**:

    {"tool_name": "Bash", "tool_input": {"command": "rm -rf /"}}

The policy guards under `implementations/` were written for an **argv** interface
(`for arg in "$@"`). Wiring the guards up without this adapter installs hooks that fire,
receive no arguments, and exit 0 -- allowing every destructive command while `coverage.json`
reports the policy as enforced. That is strictly worse than not installing them, so the
adapter exists to make the two contracts meet.

Usage (from a settings.json PreToolUse hook):
  python .chock/bin/pretooluse.py --guard <path/to/guard.sh>

Exit codes: 0 = allow, 2 = block (stderr is shown to Claude as the reason).
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# Tool inputs that carry a shell command, in priority order. Edit tools carry file content
# rather than a command and are not argv-shaped, so they are deliberately not handled here.
_COMMAND_KEYS = ("command",)


def extract_command(payload: dict) -> str:
    """Return the shell command from a pre-execution payload, or "" when there is none.

    Two payload shapes, one adapter: Claude Code's PreToolUse nests the command under
    `tool_input`; Cursor's `beforeShellExecution` carries it at the top level (with `cwd`,
    `hook_event_name`, ...). Both agents honour exit 2 as deny, so the shape is the only
    difference worth handling here.
    """
    tool_input = payload.get("tool_input")
    if isinstance(tool_input, dict):
        for key in _COMMAND_KEYS:
            value = tool_input.get(key)
            if isinstance(value, str) and value.strip():
                return value
        return ""
    for key in _COMMAND_KEYS:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return ""


# The guards exit 1 on a violation and 0 when clean. Every other outcome -- 127 for a
# missing interpreter, an OSError, a crash -- means the check did not happen.
GUARD_VIOLATION = 1

# Candidate interpreters, in probe order. `bash` on PATH is tried first, but on Windows it
# is frequently WSL's bash, which cannot see a Windows-style path and exits 1 -- identical
# to a guard reporting a violation. Trusting PATH there makes the adapter block every
# command it is asked about, so the interpreter is chosen by capability, not by name.
_BASH_CANDIDATES = (
    "bash",
    r"C:\Program Files\Git\usr\bin\bash.exe",
    r"C:\Program Files\Git\bin\bash.exe",
    r"C:\Program Files (x86)\Git\usr\bin\bash.exe",
    "/bin/bash",
    "/usr/bin/bash",
)


def find_bash(guard: Path) -> str | None:
    """First interpreter that can actually see `guard`, or None.

    The probe runs `test -f <guard>` rather than `--version`: the question is not whether
    a bash exists but whether *this* bash can resolve the path we are about to hand it.
    """
    for candidate in _BASH_CANDIDATES:
        try:
            proc = subprocess.run(
                [candidate, "-c", f'test -f "{guard.as_posix()}"'],
                capture_output=True,
                timeout=10,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        if proc.returncode == 0:
            return candidate
    return None


def run_guard(guard: Path, command: str) -> bool | None:
    """True when the guard ran and reported a violation, False when it ran clean.

    None means the check did not happen -- unparseable command, no usable bash, a crash.
    That is distinct from False and must stay distinct: every "not checked" path still
    allows, so folding it into False changes no verdict, but it would let the outcome log
    record a passing guard for a check that never ran. Evidence of a pass that nobody
    gathered is worse than no evidence.

    Nothing here blocks on its own failure. Treating "could not run" as a violation would
    stop every Bash call the moment bash was missing -- turning a best-effort guard into a
    total outage. Failing open is stated loudly on stderr instead of silently.
    """
    try:
        args = shlex.split(command)
    except ValueError:
        # Unbalanced quotes: we cannot faithfully reconstruct argv, so we must not pretend
        # to have checked it. Allow, and say so, rather than block on our own parse failure.
        print(f"chock: could not parse command, not checked: {command}", file=sys.stderr)
        return None
    if not args:
        return None

    bash = find_bash(guard)
    if bash is None:
        print(f"chock: no usable bash found, {guard.name} not checked", file=sys.stderr)
        return None

    try:
        # Explicit encoding, not the locale's: a guard that prints a non-cp1252 byte would
        # otherwise raise UnicodeDecodeError on Windows and take the adapter down with it.
        proc = subprocess.run(
            [bash, str(guard), *args], capture_output=True, text=True, encoding="utf-8", errors="replace"
        )
    except (OSError, UnicodeError) as exc:
        print(f"chock: guard could not run, not checked: {exc}", file=sys.stderr)
        return None

    if proc.returncode == GUARD_VIOLATION:
        sys.stderr.write(proc.stdout or "")
        sys.stderr.write(proc.stderr or "")
        return True
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip().splitlines()
        print(
            f"chock: guard exited {proc.returncode}, not checked" + (f": {detail[0][:120]}" if detail else ""),
            file=sys.stderr,
        )
        return None
    return False


# -------------------------------------------------------------------------- outcome log
# The same local JSONL the gate runner writes, for the same reason: without it, "does this
# guard ever fire, and does it fire wrongly" has no answer. This surface sees far more
# events than the git hook, because it is consulted on every Bash call.
#
# Duplicated from gate/runner.py rather than shared. Both files are vendored into adopter
# repos as ONE self-contained, stdlib-only file each, and a repo with only PreToolUse
# policies never receives gate.py -- so importing across them would break on exactly the
# repos this surface exists for. tests/test_gate_logging.py pins the two copies to the same
# filename, env var and rotation size so they cannot drift apart unnoticed.
GATE_LOG_ENV = "CHOCK_GATE_LOG"
_LOG_MAX_BYTES = 1_048_576


def _log_outcome(guard: Path, tool: str, blocked: bool) -> None:
    """Append one outcome record. Best effort: never raises, never changes the verdict.

    Deliberately records NO command and no guard output. The command is the scanned content
    here, and commands routinely carry bearer tokens and passwords -- writing them to a
    plaintext file on every Bash call would create the exposure the secret policies exist to
    prevent. Which policy, which tool, and allow-or-block is the whole useful signal.
    """
    try:
        if os.environ.get(GATE_LOG_ENV) == "0":
            return
        # `<...>/<policy_id>/implementations/<guard>.sh` is the shape the emitter writes.
        guard = guard.resolve()
        if guard.parent.name != "implementations":
            return
        artifact_root = None
        for parent in guard.parents:
            if (parent / ".chock").is_dir():
                artifact_root = parent / ".chock"
                break
        if artifact_root is None:
            return
        log_dir = artifact_root / "log"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / "gate-events.jsonl"
        if log_path.exists() and log_path.stat().st_size > _LOG_MAX_BYTES:
            log_path.replace(log_dir / "gate-events.1.jsonl")
        record = {
            "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "policy_id": guard.parent.parent.name,
            "surface": "pre-tool-use",
            "event": "tool_use",
            "kind": guard.stem,
            "tool": tool,
            "verdict": "block" if blocked else "allow",
        }
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:  # a guard that fails while logging must still deliver its verdict
        return


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Chock PreToolUse adapter")
    parser.add_argument("--guard", required=True, help="Path to the guard script")
    args = parser.parse_args(argv)

    raw = sys.stdin.read()
    if not raw.strip():
        return 0  # nothing to inspect
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"chock: unreadable PreToolUse payload, not checked: {exc}", file=sys.stderr)
        return 0

    command = extract_command(payload)
    if not command:
        return 0  # not a command-shaped invocation

    guard = Path(args.guard)
    if not guard.exists():
        print(f"chock: guard not found, not checked: {guard}", file=sys.stderr)
        return 0

    blocked = run_guard(guard, command)
    # Logged only when the guard actually produced a verdict. `None` is "not checked", and
    # recording it as an outcome would manufacture the evidence this log exists to collect.
    if blocked is not None:
        _log_outcome(guard, str(payload.get("tool_name") or ""), blocked)
    # Claude Code blocks on exit code 2; stderr becomes the reason shown to the agent.
    return 2 if blocked else 0


if __name__ == "__main__":
    raise SystemExit(main())
