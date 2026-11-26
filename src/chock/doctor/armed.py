"""One answer per target: is it armed? `yes` needs the hooks seen refusing (live) and the client seen calling them (heartbeat)."""

from __future__ import annotations

from chock.doctor.checks import FAIL, INFO, PASS, Check
from chock.doctor.live import ALLOWS, LIVE, PROMPT_ALLOWS, PROMPT_LIVE, PROMPT_REFUSES, REFUSES

ARMED = "armed"
YES, NO, UNKNOWN = "yes", "no", "unknown"
#: The rows that must all PASS, in the order a person fixes them.
REQUIRED = ("hooks", "launcher", "engine", REFUSES, ALLOWS, "heartbeat")
#: Present only where chock wrote a prompt-submit hook: then they must PASS too.
PROMPT_ROWS = (PROMPT_REFUSES, PROMPT_ALLOWS)
_NOT_RUN = "--live was not given, so no hook was run"


def _first_missing(found: list[Check], required: tuple[str, ...]) -> str:
    names = {c.name: c for c in found}
    for name in required:
        row = names.get(name)
        if row is None:
            skipped = [c.detail for c in found if c.name in (LIVE, PROMPT_LIVE) and c.status == INFO]
            return "; ".join(skipped) or _NOT_RUN
        if row.status != PASS:
            return f"{name} is {row.status}: {row.detail}"
    return ""


def answer(found: list[Check]) -> tuple[str, Check]:
    """(`yes`, `no` or `unknown`, the `armed` row) from a target's other rows."""
    broken = next((c for c in found if c.status == FAIL), None)
    if broken is not None:
        return NO, Check(FAIL, ARMED, f"{NO}: {broken.name} failed: {broken.detail}", broken.fix)
    prompt_hooked = any(c.name in (*PROMPT_ROWS, PROMPT_LIVE) for c in found)
    missing = _first_missing(found, REQUIRED + (PROMPT_ROWS if prompt_hooked else ()))
    if missing:
        return UNKNOWN, Check(INFO, ARMED, f"{UNKNOWN}: {missing}")
    return YES, Check(PASS, ARMED, f"{YES}: the hooks refuse and allow as they should, and the client has called them")
