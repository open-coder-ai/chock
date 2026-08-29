"""Run a guard script against a shell command, and log the verdict.

The one piece of `gate/pretooluse.py`'s old logic that survives the move to agentseam's
bundler: recognizing which vendor sent a payload and speaking its dialect back is now
agentseam's job (`bundler.bundle(agent)`), but *running the guard* was always chock's own,
and stays chock's own.

Used two ways, so it stays stdlib-only on purpose: a normal import for chock's own eval
harness (`eval/execute.py`, which replays a guard exactly as the runtime would invoke it),
and source-extracted verbatim (see `gate.runtime_bundle`) into each vendored per-agent
runtime, which must import nothing beyond the standard library.
"""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

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

GATE_LOG_ENV = "CHOCK_GATE_LOG"
_LOG_MAX_BYTES = 1_048_576


def guard_path_from_argv(argv: list[str]) -> Path | None:
    """The `--guard <path>` argument a vendored runtime was invoked with, or None.

    Read straight off argv rather than through argparse: every event a vendored runtime is
    ever invoked for goes through the same command line, chosen at install time
    (`hooks/*_install.py`), so there is nothing else on it to parse.
    """
    if "--guard" in argv:
        i = argv.index("--guard")
        if i + 1 < len(argv):
            return Path(argv[i + 1])
    return None


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
    record a passing guard for a check that never ran.

    Nothing here blocks on its own failure. Treating "could not run" as a violation would
    stop every Bash call the moment bash was missing -- turning a best-effort guard into a
    total outage. Failing open is stated loudly on stderr instead of silently.
    """
    try:
        args = shlex.split(command)
    except ValueError:
        # Unbalanced quotes: we cannot faithfully reconstruct argv, so we must not pretend
        # to have checked it. Allow, and say so, rather than block on our own parse failure.
        # The command itself is not echoed here -- it routinely carries bearer tokens and
        # passwords (same reasoning as log_outcome's redaction below), and a stderr line an
        # agent's transcript can capture is not a safe place to repeat one back verbatim.
        print("chock: could not parse command (unbalanced quotes), not checked", file=sys.stderr)
        return None
    if not args:
        return None

    bash = find_bash(guard)
    if bash is None:
        print(f"chock: no usable bash found, {guard.name} not checked", file=sys.stderr)
        return None

    try:
        # CHOCK_RAW_COMMAND carries the untokenized command so a guard can pattern-match on
        # text POSIX shlex mangles -- Windows paths lose their backslashes (C:\x -> C:x) and
        # PowerShell long flags split into characters (-Recurse -> -R -e -c ...).
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
            # empty stderr as a FAILED hook and lets the command through -- so a silent
            # guard would become a silent ALLOW, the precise failure this project exists to
            # refuse. Every other client simply shows this line.
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


def log_outcome(guard: Path, tool: str, blocked: bool) -> None:
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
    except Exception:  # a guard that fails while logging must still deliver its verdict
        return


def evaluate(argv: list[str], command: str, tool: str = "") -> str | None:
    """Run the guard named on `argv` (`--guard <path>`) against `command`.

    Returns the deny reason when the guard reports a violation, None on allow (including
    every "not checked" case -- the guard's own stderr already explains those). The one
    caller-facing entry point `gate.runtime_bundle`'s spliced handler uses: locate the
    guard, run it, log the outcome, word the verdict.
    """
    guard = guard_path_from_argv(argv)
    if guard is None or not guard.exists():
        return None
    blocked = run_guard(guard, command)
    if blocked is not None:
        log_outcome(guard, tool, blocked)
    return f"Blocked by chock policy: {guard.stem}" if blocked else None
