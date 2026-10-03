"""The engine's one time budget, shared by every hook path. Stdlib only; never imports chock.

A client's hook timeout fails OPEN, while the engine's own timers ask a person or deny, so the
engine must always run out first. One hook invocation spends ONE budget across every subprocess
it starts (git, a shell probe, the guard, the gate runner), each getting what is left of it.
"""

from __future__ import annotations

import subprocess
import time

#: Seconds one hook invocation may spend judging, after interpreter start-up. The emitted client
#: timeout is this plus a start-up margin (chock.compile.emitters.in_agent_hooks).
ENGINE_BUDGET_SECONDS = 30


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
