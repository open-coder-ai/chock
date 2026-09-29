"""What the vendored gate runner's exit code means to an agent hook, and the decision it earns."""

from __future__ import annotations

from .guard_runner import VERDICT_DENY, VERDICT_ESCALATE

GATE_BLOCKED = "blocked"
GATE_CLEAN = "clean"
GATE_ERRORED = "errored"
GATE_ASKED = "asked"
GATE_WARNED = "warned"

VERDICT_WARN = "warn"

#: The runner's exit code for an agent event, by outcome. 3 and 4 are the command-guard contract's own
#: (ask, warn); any other code is a runner that could not judge.
_EXIT_OUTCOME = {0: GATE_CLEAN, 1: GATE_BLOCKED, 3: GATE_ASKED, 4: GATE_WARNED}


def runner_outcome(returncode, stderr):
    """(outcome, message) for the runner's exit code and stderr: its words, only when it refused or spoke."""
    outcome = _EXIT_OUTCOME.get(returncode, GATE_ERRORED)
    return outcome, "" if outcome == GATE_CLEAN else (stderr or "").strip()


def gate_decision(outcome, message, gate):
    """The decision an outcome earns, or None when the gate allowed: deny, escalate (ask) or warn."""
    policy = gate.parent.parent.name
    spoken = {
        GATE_BLOCKED: (VERDICT_DENY, message or f"Blocked by chock policy: {policy}"),
        GATE_ASKED: (VERDICT_ESCALATE, message or f"Chock policy {policy} asks before this write."),
        GATE_WARNED: (VERDICT_WARN, message or f"Chock policy {policy} warns about this write."),
        GATE_ERRORED: (
            VERDICT_DENY,
            f"chock could not check this write: {message}. Refusing rather than reporting an "
            "allow it never established.",
        ),
    }
    return spoken.get(outcome)
