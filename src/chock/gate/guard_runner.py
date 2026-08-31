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

# A guard that hangs (stdin, a lock, the network) must not hang the tool call it is gating.
# 30s is generous for a guard script's actual work (a dependency check, a pattern match) while
# still bounding the worst case; a timeout is "could not run", same as any other guard crash.
_GUARD_TIMEOUT_SECONDS = 30

# What `run_guard` observed. Four words rather than the older `bool | None`, because the two
# "did not check" outcomes are no longer answered the same way and a two-valued "not checked"
# cannot tell them apart:
#
#   GUARD_UNCHECKED  a PRECONDITION failed, so the guard never started -- no interpreter that
#                    can see it, a command POSIX shlex cannot tokenize, nothing to tokenize.
#                    A property of the machine or of the command's spelling, not evidence that
#                    anything went wrong with the control.
#   GUARD_ERRORED    the guard STARTED and did not deliver a verdict -- it crashed, exited a
#                    code that is neither 0 nor 1, or hit the timeout above. The control was
#                    installed, reachable and runnable, and still produced no answer.
#
# The split exists because only the second is anomalous. `evaluate` asks for confirmation on
# it and stays silent on the first. `docs/enforcement-surfaces.md` ("What happens when the
# guard cannot decide") carries the per-path reasoning and the per-client evidence, cited to
# vendor source or vendor docs at a named ref, for what an `ask` becomes on the wire.
GUARD_BLOCKED = "blocked"
GUARD_CLEAN = "clean"
GUARD_UNCHECKED = "unchecked"
GUARD_ERRORED = "errored"

# `evaluate`'s outcome words, spelled to match `agentseam.contract.DENY` / `.ASK` exactly --
# the vendored runtime compares them against the contract's own constants, which the bundle
# embeds verbatim, and `test_guard_fail_to_ask.py` pins the two spellings equal so they
# cannot drift apart in a release where only one side moves.
VERDICT_DENY = "deny"
VERDICT_ASK = "ask"


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


def run_guard(guard: Path, command: str) -> str:
    """`GUARD_BLOCKED` / `GUARD_CLEAN` when the guard ran, otherwise why it did not.

    The two "did not check" words are the whole point of the return type, and they are not
    interchangeable. `GUARD_UNCHECKED` is a precondition -- no bash that can see the guard,
    a command POSIX shlex will not tokenize -- and is the machine's or the command's
    property. `GUARD_ERRORED` is the guard itself: it started, and it crashed, timed out, or
    exited a code that means nothing. Only the second says something went wrong with the
    control, and only the second is worth interrupting a developer over; see `evaluate`.

    Nothing here blocks on its own failure. Treating "could not run" as a violation would
    stop every Bash call the moment bash was missing -- turning a best-effort guard into a
    total outage. Every path still says what happened on stderr rather than going silent.
    """
    try:
        args = shlex.split(command)
    except ValueError:
        # Unbalanced quotes: we cannot faithfully reconstruct argv, so we must not pretend
        # to have checked it. Allow, and say so, rather than block on our own parse failure.
        # NOT an ask: a POSIX-unparseable command is common and usually benign (PowerShell
        # quoting, a Windows path), so prompting here would prompt constantly and teach the
        # habit of clicking through -- which costs the prompts that matter.
        # The command itself is not echoed here -- it routinely carries bearer tokens and
        # passwords (same reasoning as log_outcome's redaction below), and a stderr line an
        # agent's transcript can capture is not a safe place to repeat one back verbatim.
        print("chock: could not parse command (unbalanced quotes), not checked", file=sys.stderr)
        return GUARD_UNCHECKED
    if not args:
        # Nothing to check. The one path with no stderr line, because there is no command to
        # report an unchecked verdict about.
        return GUARD_UNCHECKED

    bash = find_bash(guard)
    if bash is None:
        # Also not an ask. This is uniform -- it holds for every command on the machine, not
        # for this one -- so an ask here prompts on 100% of tool calls for a whole platform
        # (Windows without Git Bash) rather than flagging an anomaly. The fix is an install
        # step, and the plugin descriptions already name this exact condition.
        print(f"chock: no usable bash found, {guard.name} not checked", file=sys.stderr)
        return GUARD_UNCHECKED

    try:
        # CHOCK_RAW_COMMAND carries the untokenized command so a guard can pattern-match on
        # text POSIX shlex mangles -- Windows paths lose their backslashes (C:\x -> C:x) and
        # PowerShell long flags split into characters (-Recurse -> -R -e -c ...).
        env = {**os.environ, "CHOCK_RAW_COMMAND": command}
        proc = subprocess.run(
            [bash, str(guard), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            timeout=_GUARD_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        # Deliberately NOT `{exc}`. TimeoutExpired's own str() is
        # "Command '['bash', '/path/guard.sh', 'curl', '-H', 'Authorization: Bearer sk-...']'
        # timed out after 30 seconds" -- it embeds `cmd`, which is bash, the guard, and every
        # token of the command. That is the one thing this module refuses to write anywhere a
        # transcript can capture (see the shlex branch above and log_outcome below), and it
        # was reaching stderr on every guard that hung. The timeout is the whole message; the
        # command adds nothing a reader needs and carries the credential.
        print(
            f"chock: guard timed out after {_GUARD_TIMEOUT_SECONDS}s, not checked",
            file=sys.stderr,
        )
        return GUARD_ERRORED
    except (OSError, UnicodeError) as exc:
        # These two are safe to print: OSError names the interpreter it could not spawn and
        # UnicodeError names an offset, neither of which is the command.
        print(f"chock: guard could not run, not checked: {exc}", file=sys.stderr)
        return GUARD_ERRORED

    if proc.returncode == GUARD_VIOLATION:
        sys.stderr.write(proc.stdout or "")
        sys.stderr.write(proc.stderr or "")
        if not ((proc.stdout or "") + (proc.stderr or "")).strip():
            # A deny with no reason is not universally a deny. Codex records exit 2 with an
            # empty stderr as a FAILED hook and lets the command through -- so a silent
            # guard would become a silent ALLOW, the precise failure this project exists to
            # refuse. Every other client simply shows this line.
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


def evaluate(argv: list[str], command: str, tool: str = "") -> tuple[str, str] | None:
    """Run the guard named on `argv` (`--guard <path>`) against `command`.

    Returns `(VERDICT_DENY, reason)` when the guard reported a violation,
    `(VERDICT_ASK, reason)` when the guard ran and could not deliver one, and None to allow.
    The one caller-facing entry point `gate.runtime_bundle`'s spliced handler uses: locate
    the guard, run it, log the outcome, word the verdict.

    **The ask is per cause, not a blanket posture, and the causes are not symmetrical.** A
    guard that crashed or timed out is rare and means the control genuinely did not run, so
    a developer is asked. A command that will not tokenize, or a machine with no bash, is
    common or uniform: asking there would prompt on a large fraction of tool calls and train
    the habit of approving without reading, which costs the prompts that matter more than
    the coverage gains. `run_guard`'s two "did not check" words carry that distinction and
    this is the only place that acts on it.

    **What an ask becomes depends on the client, and no client silently turns it into an
    allow** -- which is what would have made this change cosmetic. Claude Code and VS Code
    agent mode prompt (VS Code's `ask` also overrides its own auto-approve); Cursor's
    `beforeShellExecution`, the event chock installs, honours `permission: "ask"`; Codex
    CLI rejects `ask` at PreToolUse outright, so agentseam's adapter degrades it to a deny
    there rather than emit a value the vendor's parser fails open on. Evidence, with vendor
    source and doc citations at named refs, is in `docs/enforcement-surfaces.md`.

    Nothing is logged for the ask. `log_outcome` records only checks that HAPPENED, and
    `gatelog.summarize` buckets every non-`block` record as an allow -- so writing an ask
    record there would report an unchecked command as a passing one, the precise
    misreporting the "not checked" paths have always been kept out of the log to avoid. A
    per-cause counter in `chock status --only log` is the follow-up, not this change.
    """
    guard = guard_path_from_argv(argv)
    if guard is None or not guard.exists():
        return None
    verdict = run_guard(guard, command)
    if verdict in (GUARD_BLOCKED, GUARD_CLEAN):
        log_outcome(guard, tool, verdict == GUARD_BLOCKED)
    if verdict == GUARD_BLOCKED:
        return (VERDICT_DENY, f"Blocked by chock policy: {guard.stem}")
    if verdict == GUARD_ERRORED:
        # No command text, for log_outcome's reason: a confirmation prompt is rendered into
        # the client's UI and its transcript, and commands routinely carry credentials.
        return (
            VERDICT_ASK,
            f"chock could not check this command: the {guard.stem} guard did not complete "
            f"(see this hook's stderr). Approving runs it unchecked.",
        )
    return None
