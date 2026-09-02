"""Run a guard script against a shell command, and log the verdict."""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

GUARD_VIOLATION = 1

_BASH_CANDIDATES = (
    "bash",
    r"C:\Program Files\Git\usr\bin\bash.exe",
    r"C:\Program Files\Git\bin\bash.exe",
    r"C:\Program Files (x86)\Git\usr\bin\bash.exe",
    "/bin/bash",
    "/usr/bin/bash",
)

GATE_LOG_ENV = "CHOCK_GATE_LOG"
_LOG_MAX_BYTES = 1_048_576

_GUARD_TIMEOUT_SECONDS = 30

GUARD_BLOCKED = "blocked"
GUARD_CLEAN = "clean"
GUARD_UNCHECKED = "unchecked"
GUARD_ERRORED = "errored"

VERDICT_DENY = "deny"
VERDICT_ESCALATE = "escalate"


def guard_path_from_argv(argv: list[str]) -> Path | None:
    """The `--guard <path>` argument a vendored runtime was invoked with, or None."""
    if "--guard" in argv:
        i = argv.index("--guard")
        if i + 1 < len(argv):
            return Path(argv[i + 1])
    return None


def find_bash(guard: Path) -> str | None:
    """First interpreter that can actually see `guard`, or None."""
    for candidate in _BASH_CANDIDATES:
        try:
            proc = subprocess.run(  # noqa: S603 -- probing candidate shells is this function's job
                [candidate, "-c", f'test -f "{guard.as_posix()}"'],
                capture_output=True,
                timeout=10,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        if proc.returncode == 0:
            return candidate
    return None


def run_guard(guard: Path, command: str) -> str:
    """`GUARD_BLOCKED` / `GUARD_CLEAN` when the guard ran, otherwise why it did not."""
    try:
        args = shlex.split(command)
    except ValueError:
        print("chock: could not parse command (unbalanced quotes), not checked", file=sys.stderr)
        return GUARD_UNCHECKED
    if not args:
        return GUARD_UNCHECKED

    bash = find_bash(guard)
    if bash is None:
        print(f"chock: no usable bash found, {guard.name} not checked", file=sys.stderr)
        return GUARD_UNCHECKED

    try:
        env = {**os.environ, "CHOCK_RAW_COMMAND": command}
        proc = subprocess.run(  # noqa: S603 -- running the guard script against the command is the feature
            [bash, str(guard), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            timeout=_GUARD_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired:
        print(
            f"chock: guard timed out after {_GUARD_TIMEOUT_SECONDS}s, not checked",
            file=sys.stderr,
        )
        return GUARD_ERRORED
    except (OSError, UnicodeError) as exc:
        print(f"chock: guard could not run, not checked: {exc}", file=sys.stderr)
        return GUARD_ERRORED

    if proc.returncode == GUARD_VIOLATION:
        sys.stderr.write(proc.stdout or "")
        sys.stderr.write(proc.stderr or "")
        if not ((proc.stdout or "") + (proc.stderr or "")).strip():
            print(f"chock: blocked by {Path(guard).name} (guard gave no reason)", file=sys.stderr)
        return GUARD_BLOCKED
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip().splitlines()
        print(
            f"chock: guard exited {proc.returncode}, not checked" + (f": {detail[0][:120]}" if detail else ""),
            file=sys.stderr,
        )
        return GUARD_ERRORED
    return GUARD_CLEAN


def log_outcome(guard: Path, tool: str, *, blocked: bool) -> None:
    """Append one outcome record. Best effort: never raises, never changes the verdict."""
    try:
        if os.environ.get(GATE_LOG_ENV) == "0":
            return
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
        import json

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
    except Exception:  # noqa: BLE001 -- best effort logging: never raises, never changes the verdict
        return


def evaluate(argv: list[str], command: str, tool: str = "") -> tuple[str, str] | None:
    """Run the guard named on `argv` (`--guard <path>`) against `command`."""
    guard = guard_path_from_argv(argv)
    if guard is None or not guard.exists():
        return None
    verdict = run_guard(guard, command)
    if verdict in (GUARD_BLOCKED, GUARD_CLEAN):
        log_outcome(guard, tool, blocked=verdict == GUARD_BLOCKED)
    if verdict == GUARD_BLOCKED:
        return (VERDICT_DENY, f"Blocked by chock policy: {guard.stem}")
    if verdict == GUARD_ERRORED:
        return (
            VERDICT_ESCALATE,
            f"chock could not check this command: the {guard.stem} guard did not complete "
            f"(see this hook's stderr). Approving runs it unchecked.",
        )
    return None
