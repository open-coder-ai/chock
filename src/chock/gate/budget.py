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
import contextvars
import json
import os
import queue
import signal
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


#: A member's own deadline (absolute monotonic instant) in a multi-policy hook; each member's thread sets it,
#: so it never reaches another thread. Unset, `engine_deadline` is today's single-policy budget.
MEMBER_DEADLINE = contextvars.ContextVar("chock_member_deadline", default=None)


def engine_deadline():
    """The monotonic instant this invocation's budget runs out: the member's own deadline when one is set."""
    member = MEMBER_DEADLINE.get()
    return member if member is not None else time.monotonic() + ENGINE_BUDGET_SECONDS


def last_state(var):
    """This thread's mutable record in the ContextVar `var`: a thread starts with none, so none is shared."""
    state = var.get(None)
    if state is None:
        state = {}
        var.set(state)
    return state


#: Every child process tree still running, by pid: `run_tree` and the pattern judge enter theirs, so a multi-policy
#: hook can end what a member that never returned left behind before it exits.
LIVE_TREES = {}


def track_tree(proc):
    """Record `proc` (started with `tree_spawn_options`) as a tree to end if the hook leaves while it runs."""
    LIVE_TREES[proc.pid] = proc


def untrack_tree(proc):
    """Forget `proc`: it ended, or its tree was killed."""
    LIVE_TREES.pop(proc.pid, None)


def kill_live_trees():
    """Kill every tree still recorded, whichever thread started it."""
    for proc in tuple(LIVE_TREES.copy().values()):
        kill_tree(proc)
        untrack_tree(proc)


def tree_spawn_options():
    """Popen options that put a child in its own process group (POSIX session; Windows new process group)."""
    if os.name == "nt":
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


def kill_tree(proc):
    """Kill `proc` and everything it started: killpg on POSIX, `taskkill /T /F` on Windows."""
    with contextlib.suppress(OSError):
        if os.name == "nt":
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True, check=False)  # noqa: S603, S607 -- the OS tool that ends a process tree
        else:
            os.killpg(proc.pid, signal.SIGKILL)
    with contextlib.suppress(OSError):
        proc.kill()


def run_tree(argv, *, timeout=None, **options):
    """`subprocess.run` that, on a timeout, kills the child's whole process tree before raising."""
    options.pop("check", None)
    stdin_text = options.pop("input", None)
    if options.pop("capture_output", False):
        options.update(stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if stdin_text is not None:
        options["stdin"] = subprocess.PIPE
    if "text" in options or "encoding" in options:
        options["text"] = True
    with subprocess.Popen(argv, **options, **tree_spawn_options()) as proc:  # noqa: S603 -- callers pass their own fixed argv
        track_tree(proc)
        try:
            out, err = proc.communicate(stdin_text, timeout=timeout)
        except BaseException:
            kill_tree(proc)
            proc.communicate()
            raise
        finally:
            untrack_tree(proc)
    return subprocess.CompletedProcess(argv, proc.returncode, out, err)


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
        **tree_spawn_options(),
    )
    lines = queue.Queue()
    threading.Thread(target=_pump_lines, args=(proc, lines), daemon=True).start()
    judge["proc"], judge["lines"] = proc, lines
    track_tree(proc)
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
        kill_tree(proc)  # before closing stdout: the reader thread holds it until the child's EOF
    proc.wait()
    untrack_tree(proc)
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
