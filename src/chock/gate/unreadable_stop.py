"""Bound the refusals of a Stop whose payload cannot be read. Stdlib only; never imports chock.

No session id is readable then, so #208's per-session ledger cannot count it. A per-repo ledger,
`.chock/state/unreadable-stop.jsonl`, counts refusals inside a sliding window instead: up to
`REENTRY_CAP` are refused, the next ends the turn with a warning and a held gate-log record, never
silently, until the oldest refusal ages out. The ledger lives under
`.chock/state`, which protect-agent-config's shell guard covers; an agent that can edit it can pre-seed
it, the same trust the per-session ledger places in its own for clients that send no count. A ledger
that is not a regular file in real directories is never opened: only a refusal is safe.
"""

from __future__ import annotations

import contextlib
import sys
from datetime import datetime, timezone
from pathlib import Path

from .gate_outcome import VERDICT_WARN
from .guard_runner import VERDICT_DENY
from .session_log import SESSION_STATE_PARTS
from .stop_reentry import (
    REENTRY_CAP,
    STOP_LOG_BLOCK,
    STOP_LOG_WARN,
    _stop_append,
    _stop_gate_log,
    _stop_lines,
    _stop_parse,
    stop_ledger_safe,
)

UNREADABLE_STOP_LEDGER = "unreadable-stop.jsonl"
UNREADABLE_STOP_PHASE = "unreadable-stop"
UNREADABLE_STOP_WINDOW_SECONDS = 600
REENTRY_UNREADABLE = "unreadable"
_UNREADABLE_STOP_WARNING = (
    "chock {policy}: {cap} stops in a row had a payload chock could not read, so none of them was judged."
    " The turn was allowed to end so the client does not loop; a commit will judge what is on disk,"
    " and a person must look at why the payload is unreadable.\n"
)
_UNREADABLE_STOP_LAST = (
    "\nThis is refusal {cap} of {cap} for stops chock cannot read: the next one ends the turn unchecked,"
    " and a commit will judge what is on disk. A person must look at why the payload is unreadable."
)


def _unreadable_stop_recent(lines, now):
    """The refusals recorded inside the window; a record that does not parse, or has no time, counts as none."""
    kept = []
    for line in lines:
        seen = _stop_parse(line)
        stamp = seen.get("at") if isinstance(seen, dict) else None
        refused = isinstance(seen, dict) and seen.get("phase") == UNREADABLE_STOP_PHASE
        if (
            refused
            and seen.get("verdict") == STOP_LOG_BLOCK
            and type(stamp) in (int, float)
            and 0 <= now - stamp < UNREADABLE_STOP_WINDOW_SECONDS
        ):
            kept.append(stamp)
    return kept


def settle_unreadable_stop(root, policy, refusal):
    """(verdict, text) this unreadable Stop earns: a refusal with `refusal`, or a warning once the cap is spent.

    A ledger that is not a regular file in real directories, or cannot be written, keeps refusing: with nothing to count, only a refusal is safe.
    """
    path = Path(root).joinpath(*SESSION_STATE_PARTS, UNREADABLE_STOP_LEDGER)
    if not stop_ledger_safe(path):
        return VERDICT_DENY, refusal
    lines = _stop_lines(path)
    now = datetime.now(timezone.utc).timestamp()
    index = len(_unreadable_stop_recent(lines, now)) + 1
    capped = index > REENTRY_CAP
    verdict = STOP_LOG_WARN if capped else STOP_LOG_BLOCK
    _stop_append(path, lines, {"phase": UNREADABLE_STOP_PHASE, "verdict": verdict, "at": now, "reentry": index})
    _stop_gate_log(root, policy, verdict, (index, REENTRY_UNREADABLE, None), [])
    if capped:
        text = _UNREADABLE_STOP_WARNING.format(policy=policy, cap=REENTRY_CAP)
        with contextlib.suppress(Exception):  # stderr may be closed; the warning still goes out as the decision
            sys.stderr.write(text)
            sys.stderr.flush()
        return VERDICT_WARN, text
    return VERDICT_DENY, refusal + (_UNREADABLE_STOP_LAST.format(cap=REENTRY_CAP) if index == REENTRY_CAP else "")
