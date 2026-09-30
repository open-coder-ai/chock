"""Judge a turn's end again when the client re-enters its own Stop hook. Stdlib only; never imports chock.

Claude Code, Codex and Copilot send `stop_hook_active`, Cursor sends `loop_count`; none says how often.
Allowing every re-entry lets an agent that ignores the first refusal end its turn with the violation
on disk, refusing every one never ends. So each Stop of a turn is written to the session log, and a
re-entry is refused only for findings the turn was not already told about, at most `REENTRY_CAP` times.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from .session_log import session_id_of, session_log_path

#: Re-entries judged per turn. The last refusal asks for a person; the next re-entry is allowed, or
#: a client that never stops re-entering would loop for ever.
REENTRY_CAP = 3
STOP_PHASE = "stop"
STOP_DENY = "deny"
_GATE_LOG_ENV = "CHOCK_GATE_LOG"
_GATE_LOG_PARTS = (".chock", "log", "gate-events.jsonl")
_LOG_MAX_BYTES = 1_048_576
_FIRST = 0

VERDICT_CLEAN = "clean"
VERDICT_REFUSED = "refused"
VERDICT_REPORTED = "already-reported"
VERDICT_CAPPED = "cap-reached"
VERDICT_UNTRACKED = "untracked"

_PERSON = " This turn was refused {cap} times: a person must review these findings before the work is accepted."


def reentries(event):
    """How many times the client says this stop re-entered its hook: `loop_count`, else 1 for `stop_hook_active`."""
    raw = event.raw if isinstance(event.raw, dict) else {}
    try:
        counted = int(raw.get("loop_count") or 0)
    except (TypeError, ValueError):
        counted = 1
    return max(counted, 1 if raw.get("stop_hook_active") else 0)


def _fingerprint(message):
    """The findings set as a digest of the refusal that named it: never the text itself."""
    return hashlib.sha256(message.encode("utf-8", "replace")).hexdigest()[:16]


def _turn_records(path, policy):
    """This policy's Stop records since its last first Stop of the session, oldest first."""
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    turn = []
    for line in reversed(lines):
        try:
            seen = json.loads(line)
        except ValueError:
            continue
        if not isinstance(seen, dict) or seen.get("phase") != STOP_PHASE or seen.get("policy") != policy:
            continue
        turn.append(seen)
        if seen.get("reentry") == _FIRST:
            break
    return turn[::-1]


def _ledger(path, record):
    """Append a Stop record; whether it landed."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, sort_keys=True) + "\n")
    except OSError:
        return False
    return True


def _stamp():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _gate_log(root, policy, index, verdict):
    """One gate-log record per re-entry verdict; best effort, and off with `CHOCK_GATE_LOG=0`."""
    try:
        if os.environ.get(_GATE_LOG_ENV) == "0":
            return
        path = Path(root).joinpath(*_GATE_LOG_PARTS)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.stat().st_size > _LOG_MAX_BYTES:
            path.replace(path.with_name("gate-events.1.jsonl"))
        record = {
            "ts": _stamp(),
            "policy_id": policy,
            "surface": "stop-reentry",
            "event": "stop",
            "kind": "reentry",
            "reentry": index,
            "verdict": verdict,
            "match_count": 0,
            "matches": [],
        }
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001 -- a log must never change what the hook decides
        return


def _record(path, policy, index, message, *, refused):
    return {
        "ts": _stamp(),
        "session_id": path.stem,
        "phase": STOP_PHASE,
        "policy": policy,
        "reentry": index,
        "fingerprint": _fingerprint(message) if message else "",
        "verdict": STOP_DENY if refused else VERDICT_CLEAN,
    }


def _reentry_verdict(index, turn, message):
    """(verdict, refuse) for a re-entry: clean, or findings refused unless already reported or past the cap."""
    if not message:
        return VERDICT_CLEAN, False
    if index > REENTRY_CAP:
        return VERDICT_CAPPED, False
    reported = next((r.get("fingerprint") for r in reversed(turn) if r.get("verdict") == STOP_DENY), None)
    if _fingerprint(message) == reported:
        return VERDICT_REPORTED, False
    return VERDICT_REFUSED, True


def settle_stop(event, root, gate, decision):
    """The decision a Stop earns once this turn's earlier Stops are weighed against `decision`."""
    if decision is not None and decision[0] != STOP_DENY:
        return decision
    policy = gate.parent.parent.name
    path = session_log_path(root, session_id_of(event))
    signalled = reentries(event)
    message = decision[1] if decision else ""
    if not signalled:
        _ledger(path, _record(path, policy, _FIRST, message, refused=decision is not None))
        return decision
    turn = _turn_records(path, policy)
    index = max(len(turn), signalled)
    verdict, refuse = _reentry_verdict(index, turn, message)
    if not _ledger(path, _record(path, policy, index, message, refused=refuse)) and refuse:
        verdict, refuse = VERDICT_UNTRACKED, False
    _gate_log(root, policy, index, verdict)
    if not refuse:
        return None
    return STOP_DENY, message + (_PERSON.format(cap=REENTRY_CAP) if index == REENTRY_CAP else "")
