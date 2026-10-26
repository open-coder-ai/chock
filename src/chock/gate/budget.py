"""The engine's one time budget, shared by every hook path. Stdlib only; never imports chock.

A client's hook timeout fails OPEN, while the engine's own timers ask a person or deny, so the
engine must always run out first. One hook invocation spends ONE budget across every subprocess
it starts (git, a shell probe, the guard, the gate runner), each getting what is left of it.

A gate's patterns get a deadline of their own: `re` holds the GIL and no platform can interrupt
it in-process (SIGALRM reaches the main thread on POSIX only), so the patterns run in a child
interpreter the parent can kill. Functions only, no classes: the shared runtime extracts this
module's definitions (chock.gate.runtime_shared), and so does the vendored runner (chock.gate.assemble).
"""

from __future__ import annotations

import contextlib
import json
import queue
import subprocess
import sys
import threading
import time

#: Seconds one hook invocation may spend judging, after interpreter start-up. The emitted client
#: timeout is this plus a start-up margin (chock.compile.emitters.in_agent_hooks).
ENGINE_BUDGET_SECONDS = 30

#: Added to the environment of every policy script, so running a gate never writes bytecode into its pack.
BYTECODE_OFF = {"PYTHONDONTWRITEBYTECODE": "1"}

#: Seconds a gate's patterns may spend on one judgement (one commit's lines, one write, one blob)
#: before the gate refuses naming itself: a repo-supplied pattern can be catastrophic.
PATTERN_SECONDS = 10

#: Seconds a fresh judge child may take to start and say it is ready, before any pattern runs: start-up is
#: not charged to `PATTERN_SECONDS`, so a slow interpreter start is not taken for a catastrophic pattern.
PATTERN_START_SECONDS = 10

#: How a refusal opens when the child is gone; the last line it wrote to stderr follows, then `)`.
PATTERN_JUDGE_EXITED = "the pattern judge exited early ("

#: The line the child writes once its imports are done, before it reads its first request.
PATTERN_JUDGE_READY = "ready"

#: The child that runs a gate's patterns. Per request: one JSON line `[[pattern, [text, ...]], ...]`
#: in, one JSON line `[[index of each text the pattern matches], ...]` out. Python source as text
#: because every file this ships in is self-contained; `-I` keeps a planted re.py off its path.
PATTERN_JUDGE_SOURCE = (
    "import json, re, sys\n"
    "print('ready', flush=True)\n"
    "for line in sys.stdin:\n"
    "    out = []\n"
    "    for pattern, texts in json.loads(line):\n"
    "        search = re.compile(pattern).search\n"
    "        out.append([index for index, text in enumerate(texts) if search(text)])\n"
    "    print(json.dumps(out), flush=True)\n"
)


def engine_deadline():
    """The monotonic instant this invocation's budget runs out."""
    return time.monotonic() + ENGINE_BUDGET_SECONDS


def engine_remaining(deadline):
    """Seconds left before `deadline`, never negative."""
    return max(deadline - time.monotonic(), 0.0)


def time_left(deadline, cmd):
    """Seconds left for a subprocess; raises TimeoutExpired when none are, so the caller's timeout path runs."""
    left = deadline - time.monotonic()
    if left <= 0:
        raise subprocess.TimeoutExpired(cmd, 0)
    return left


def allowed_seconds(expired):
    """The time a timed-out call was actually given, as text (what the deadline left it, not the full budget)."""
    return f"{max(float(expired.timeout or 0), 0.0):.1f}s"


def pattern_judge(interpreter=None):
    """A pattern judge, not yet started: the interpreter to run the patterns in (this one by default)."""
    return {"argv": [interpreter or sys.executable, "-I", "-c", PATTERN_JUDGE_SOURCE], "proc": None, "lines": None}


def _pump_lines(proc, lines):
    for line in proc.stdout:
        lines.put(line)
    lines.put(None)


def _start_judge(judge):
    proc = subprocess.Popen(  # noqa: S603 -- the child is this module's own source, run by this interpreter
        judge["argv"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    lines = queue.Queue()
    threading.Thread(target=_pump_lines, args=(proc, lines), daemon=True).start()
    judge["proc"], judge["lines"] = proc, lines
    try:
        ready = lines.get(timeout=PATTERN_START_SECONDS)
    except queue.Empty:
        close_judge(judge)
        return f"the pattern judge did not start within {PATTERN_START_SECONDS}s"
    if ready is None or ready.strip() != PATTERN_JUDGE_READY:
        return f"{PATTERN_JUDGE_EXITED}{close_judge(judge)})"
    return None


def close_judge(judge):
    """Stop the judge's child, if one runs; the last line it wrote to stderr, or ""."""
    proc = judge["proc"]
    judge["proc"] = judge["lines"] = None
    if proc is None:
        return ""
    if proc.poll() is None:
        proc.kill()  # before closing stdout: the reader thread holds it until the child's EOF
    proc.wait()
    try:
        spoken = proc.stderr.read()
    except (OSError, ValueError):
        spoken = ""
    for stream in (proc.stdin, proc.stdout, proc.stderr):
        with contextlib.suppress(OSError):
            stream.close()
    return (spoken.strip().splitlines() or [""])[-1]


def _ensure_judge(judge):
    """None when the judge's child runs (started now if need be); otherwise why it could not."""
    if judge["proc"] is not None:
        return None
    try:
        return _start_judge(judge)
    except OSError as exc:
        return f"the pattern judge could not start ({exc})"


def judge_patterns(judge, jobs, seconds):
    """(hits, None) or (None, why): per job of (pattern, texts), the indices of the texts the pattern matches.

    A job that runs past `seconds` kills the child and names the time; a job with no text is never
    sent. `why` is text for a refusal: the judge is undecided and an undecided gate refuses.
    """
    if not any(texts for _, texts in jobs):
        return [[] for _ in jobs], None
    failed = _ensure_judge(judge)
    if failed:
        return None, failed
    proc, lines = judge["proc"], judge["lines"]
    try:
        proc.stdin.write(json.dumps(jobs) + "\n")
        proc.stdin.flush()
    except (OSError, ValueError):
        return None, f"{PATTERN_JUDGE_EXITED}{close_judge(judge)})"
    try:
        line = lines.get(timeout=seconds)
    except queue.Empty:
        close_judge(judge)
        return None, f"the patterns gave no verdict within {seconds:g}s (a catastrophic pattern?)"
    if line is None:
        return None, f"{PATTERN_JUDGE_EXITED}{close_judge(judge)})"
    return json.loads(line), None
