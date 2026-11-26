"""What the vendored gate runner's exit code means to an agent hook, and the decision it earns."""

from __future__ import annotations

import json

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


def ask_reason(policy, message, noun):
    """What a person is shown on an ask: the policy and its own message, never the matched text or the tool argument."""
    message = (message or "").strip()
    return f"Chock policy {policy} asks: {message}" if message else f"Chock policy {policy} asks before this {noun}."


def _spec(gate):
    try:
        spec = json.loads(gate.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return spec if isinstance(spec, dict) else {}


def asked_message(gate, message):
    """What the ask says: a script gate's first non-empty stderr line (the runner already made it inert; its own "chose to ask" filler is no words), else the spec's message.

    The rest of the runner's text is per-match lines, which carry the written text and stay out.
    """
    spec = _spec(gate)
    first = next((line.strip() for line in (message or "").splitlines() if line.strip()), "")
    named = str((spec.get("params") or {}).get("script", "")).replace("\\", "/").rsplit("/", 1)[-1]
    if spec.get("kind") == "script" and first and first != f"{named} chose to ask":
        return first
    return str(spec.get("message") or "").strip()


def gate_decision(outcome, message, gate):
    """The decision an outcome earns, or None when the gate allowed: deny, escalate (ask) or warn."""
    policy = gate.parent.parent.name
    spoken = {
        GATE_BLOCKED: (VERDICT_DENY, message or f"Blocked by chock policy: {policy}"),
        GATE_ASKED: (VERDICT_ESCALATE, ask_reason(policy, asked_message(gate, message), "write")),
        GATE_WARNED: (VERDICT_WARN, message or f"Chock policy {policy} warns about this write."),
        GATE_ERRORED: (
            VERDICT_DENY,
            f"chock could not check this write: {message}. Refusing rather than reporting an "
            "allow it never established.",
        ),
    }
    return spoken.get(outcome)
