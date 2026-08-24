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

    Three payload shapes, one adapter: Claude Code's PreToolUse nests the command under
    `tool_input`; Cursor's `beforeShellExecution` carries it at the top level (with `cwd`,
    `hook_event_name`, ...); Copilot CLI and VS Code agent mode (both witnessed 2026-08-23)
    put it under `toolArgs`, frequently as a JSON *string* that must be parsed again. All
    honour exit 2 as deny, so the payload shape is the only difference worth handling here.
    """
    tool_input = payload.get("tool_input")
    if isinstance(tool_input, dict):
        for key in _COMMAND_KEYS:
            value = tool_input.get(key)
            if isinstance(value, str) and value.strip():
                return value
        return ""
    # Copilot CLI / VS Code agent mode: {toolName, toolArgs}. toolArgs is JSON, and is
    # frequently a JSON string (double-encoded) rather than an object -- parse it once more.
    tool_args = payload.get("toolArgs")
    if isinstance(tool_args, str):
        try:
            tool_args = json.loads(tool_args)
        except (ValueError, TypeError):
            tool_args = None
    if isinstance(tool_args, dict):
        for key in _COMMAND_KEYS:
            value = tool_args.get(key)
            if isinstance(value, str) and value.strip():
                return value
        return ""
    for key in _COMMAND_KEYS:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return ""


def is_codex_payload(payload: dict) -> bool:
    """True for Codex's PreToolUse envelope.

    Codex sends Claude's `tool_input` shape plus turn identifiers (`turn_id`,
    `permission_mode`) that Claude Code does not. The distinction matters because the two
    clients need OPPOSITE deny exits: Claude blocks on exit 2, while on Windows Codex
    wraps hook commands in `powershell -Command`, which collapses exit 2 into 1 -- a
    FAILED hook that fails open. Codex's only stdout-parsing arm is exit 0, so its deny
    must ride in JSON with a clean exit. If this test ever misfires on a future Claude
    payload the failure is benign: Claude Code honours the same exit-0
    `permissionDecision` output.
    """
    return isinstance(payload, dict) and isinstance(payload.get("tool_input"), dict) and "turn_id" in payload


def is_cursor_payload(payload: dict) -> bool:
    """True for Cursor's `beforeShellExecution` envelope.

    Cursor carries the command at the top level alongside `cwd`/`sandbox`, where Claude
    nests it under `tool_input` and Copilot under `toolArgs`. Recognising the shape lets
    the deny response be spoken in Cursor's dialect without changing what the other
    clients receive.
    """
    if not isinstance(payload, dict):
        return False
    if isinstance(payload.get("tool_input"), dict) or payload.get("toolArgs") is not None:
        return False
    return isinstance(payload.get("command"), str) and ("cwd" in payload or "sandbox" in payload)


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
        #
        # CHOCK_RAW_COMMAND carries the untokenized command so a guard can pattern-match on
        # text POSIX shlex mangles -- Windows paths lose their backslashes (C:\x -> C:x) and
        # PowerShell long flags split into characters (-Recurse -> -R -e -c ...). A guard
        # that needs to recognise PowerShell/Windows syntax reads the raw string; the argv
        # stays the primary input, so guards that do not look at it are unaffected.
        env = {**os.environ, "CHOCK_RAW_COMMAND": command}
        proc = subprocess.run(
            [bash, str(guard), *args], capture_output=True, text=True, encoding="utf-8", errors="replace", env=env
        )
    except (OSError, UnicodeError) as exc:
        print(f"chock: guard could not run, not checked: {exc}", file=sys.stderr)
        return None

    if proc.returncode == GUARD_VIOLATION:
        sys.stderr.write(proc.stdout or "")
        sys.stderr.write(proc.stderr or "")
        if not ((proc.stdout or "") + (proc.stderr or "")).strip():
            # A deny with no reason is not universally a deny. Codex records exit 2 with an
            # empty stderr as a FAILED hook ("did not write a blocking reason to stderr",
            # codex-rs/hooks/src/events/pre_tool_use.rs) and lets the command through -- so a
            # silent guard would become a silent ALLOW, the precise failure this project
            # exists to refuse. Every other client simply shows this line.
            print(f"chock: blocked by {Path(guard).name} (guard gave no reason)", file=sys.stderr)
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

    # Read BYTES and decode UTF-8 ourselves rather than letting `sys.stdin.read()` apply
    # the platform locale. On Windows that locale is cp1252, which turned Cursor's
    # UTF-8 BOM into the three characters 'ï»¿' -- json.loads then failed with
    # "Expecting value: line 1 column 1", the adapter reported "not checked", and
    # returned 0. Every command was ALLOWED while the package claimed enforcement.
    # Witnessed on a real Cursor install, found only because the probe logged the raw
    # payload instead of trusting the verdict. `utf-8-sig` also drops the BOM, and
    # `errors="replace"` keeps a stray byte from silently disabling the guard.
    try:
        raw = sys.stdin.buffer.read().decode("utf-8-sig", errors="replace")
    except (AttributeError, ValueError):  # no binary stdin (embedded/test harnesses)
        raw = sys.stdin.read().lstrip("\ufeff")
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
        # Claude/Cursor use tool_name; Copilot/VS Code use toolName -- record either.
        _log_outcome(guard, str(payload.get("tool_name") or payload.get("toolName") or ""), blocked)
    if blocked and not is_cursor_payload(payload) and isinstance(payload.get("tool_input"), dict):
        # Claude protocol (Claude Code and Codex). Exit 2 alone was witnessed NOT blocking
        # a trusted Codex plugin hook -- the command ran with the reason on stderr -- so the
        # decision is stated explicitly as well. This is Claude Code's own documented
        # PreToolUse output, which Codex implements, not a per-vendor special case.
        print(
            json.dumps(
                {
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "permissionDecision": "deny",
                        "permissionDecisionReason": f"Blocked by chock policy: {guard.stem}",
                    }
                }
            )
        )
    if blocked and is_cursor_payload(payload):
        # Cursor documents exit 2 as "equivalent to returning permission: deny", but a
        # plugin hook returning exit 2 was witnessed NOT blocking on a real install --
        # the command ran. The stdout JSON is what Cursor actually honours, so both are
        # sent: the JSON for Cursor, the exit code for every other client.
        reason = f"Blocked by chock policy: {guard.stem}"
        print(
            json.dumps(
                {
                    "permission": "deny",
                    "user_message": reason,
                    "agent_message": f"{reason}. This command is refused by repository policy.",
                }
            )
        )
    if blocked and is_codex_payload(payload):
        # The deny is already on stdout (hookSpecificOutput above). Exit 0 is the only
        # arm of Codex's parser that reads it; exit 2 would be collapsed to 1 by the
        # PowerShell wrapper Codex uses on Windows and discarded as a failed hook.
        # Witnessed blocking with 0, witnessed running with 2.
        return 0
    # Claude Code blocks on exit code 2; stderr becomes the reason shown to the agent.
    return 2 if blocked else 0


if __name__ == "__main__":
    raise SystemExit(main())
