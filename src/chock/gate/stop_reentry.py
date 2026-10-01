"""Judge a turn's end again when the client re-enters its own Stop hook. Stdlib only; never imports chock.

Claude Code, Codex and Copilot send `stop_hook_active`, Cursor sends `loop_count`. While findings
remain, every re-entry is refused, up to `REENTRY_CAP`; past it the turn ends with a warning the
user sees and a held gate-log record, never silently. The count is kept per session in
`.chock/state/<session_id>.stop.jsonl`; see spec/session-log.md.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from .gate_outcome import VERDICT_WARN
from .guard_runner import GATE_LOG_ENV, VERDICT_DENY, append_gate_log
from .session_log import (
    SESSION_ID_MAX,
    SESSION_MAX_ENTRIES,
    SESSION_STATE_PARTS,
    SESSION_TRIM_BYTES,
    _prune_old,
    session_id_of,
)

#: Re-entries refused per turn while findings remain. The next one ends the turn with a warning,
#: or a client with no cap of its own would loop for ever.
REENTRY_CAP = 3
STOP_LEDGER_SUFFIX = ".stop.jsonl"
#: st_mode type bits: a ledger is a regular file in real directories, nothing else.
GATE_LOG_PARTS = (".chock", "log", "gate-events.jsonl")
STOP_MODE_MASK = 0o170000
STOP_MODE_FILE = 0o100000
STOP_MODE_DIR = 0o040000
STOP_PHASE = "stop"
#: The vendor's own id for the turn, where it sends one: Codex `turn_id`, Cursor `generation_id`.
STOP_TURN_KEYS = ("turn_id", "generation_id")
STOP_COUNT_KEY = "loop_count"
STOP_DIGEST_CHARS = 16

REENTRY_CLEAN = "clean"
REENTRY_REFUSED = "refused"
REENTRY_CAPPED = "cap-reached"
REENTRY_UNTRACKED = "untracked"
#: What the gate log calls each outcome, in the words `chock status` counts.
STOP_LOG_BLOCK = "block"
STOP_LOG_ALLOW = "allow"
STOP_LOG_WARN = "warn"

_STOP_LAST = (
    "\nThis is refusal {cap} of {cap} for this turn's end: the next stop ends the turn with these findings"
    " still on disk, and a commit will refuse them. A person must review them."
)
_STOP_WARNING = (
    "chock {policy}: this turn ended with findings still on disk{why}. The turn was allowed to end so the"
    " client does not loop; a commit will refuse these findings, and a person must review them.\n"
)
_STOP_WHY = {
    REENTRY_CAPPED: " after {cap} refused stops",
    REENTRY_UNTRACKED: " (the stop record under .chock/state could not be written, so re-entries cannot be counted)",
}
_STOP_SINCE = {True: " (changed since the last refusal)", False: " (unchanged since the last refusal)"}


def reentries(event):
    """How many times the client says this stop re-entered its hook: `loop_count`, else 1 for `stop_hook_active`."""
    raw = event.raw if isinstance(event.raw, dict) else {}
    try:
        counted = int(raw.get(STOP_COUNT_KEY) or 0)
    except (TypeError, ValueError):
        counted = 1
    return max(counted, 1 if raw.get("stop_hook_active") else 0)


def _stop_turn(event):
    """The vendor's turn id, when the payload carries one; None otherwise."""
    raw = event.raw if isinstance(event.raw, dict) else {}
    for key in STOP_TURN_KEYS:
        value = raw.get(key)
        if isinstance(value, str) and value:
            return value[:SESSION_ID_MAX]
    return None


def _stop_digest(*parts):
    digest = hashlib.sha256()
    for part in parts:
        digest.update(str(part).encode("utf-8", "replace") + b"\0")
    return digest.hexdigest()[:STOP_DIGEST_CHARS]


def finding_digests(message, writes):
    """One digest per flagged file, of its path and content: never the text itself, never the message's wording."""
    if not message:
        return []
    lines = [line.strip().lstrip("-").strip() for line in message.splitlines()]
    flagged = [p for p in writes if any(line.startswith(p + ":") for line in lines)] or list(writes)
    if not flagged:
        return [_stop_digest(message)]
    return sorted({_stop_digest(p, writes[p]) for p in flagged})


def stop_ledger_path(root, session_id):
    return Path(root).joinpath(*SESSION_STATE_PARTS, session_id + STOP_LEDGER_SUFFIX)


def stop_ledger_safe(path):
    """Whether `path`, its directory and `.chock` are what chock made: real directories and a regular file or none.

    lstat, so a symlink, FIFO, socket, device or directory in any place is refused before anything opens it:
    opening a FIFO blocks the hook until its timeout, which a client may read as an allow.
    """
    for target, kind in ((path, STOP_MODE_FILE), (path.parent, STOP_MODE_DIR), (path.parent.parent, STOP_MODE_DIR)):
        try:
            mode = os.lstat(target).st_mode
        except FileNotFoundError:
            continue
        except OSError:
            return False
        if mode & STOP_MODE_MASK != kind:
            return False
    return True


def _stop_lines(path):
    """The ledger's lines; none when it is missing, unsafe or cannot be read."""
    if not stop_ledger_safe(path):
        return []
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
        with os.fdopen(fd, encoding="utf-8", errors="replace") as fh:
            return fh.read().splitlines()
    except OSError:
        return []


def _stop_parse(line):
    try:
        return json.loads(line)
    except (ValueError, RecursionError):
        return None


def _stop_well_formed(seen, session_id):
    stamp, index = seen.get("ts"), seen.get("reentry")
    return (
        isinstance(stamp, str)
        and bool(stamp)
        and seen.get("session_id") == session_id
        and type(index) is int
        and index >= 0
    )


def _stop_chain(lines, session_id, policy, turn):
    """This turn's records, newest first, counting down without a gap to its first stop; None when broken."""
    chain = []
    for line in reversed(lines):
        seen = _stop_parse(line)
        if not isinstance(seen, dict) or seen.get("phase") != STOP_PHASE or seen.get("policy") != policy:
            continue
        if turn is not None and seen.get("turn") != turn:
            continue
        if not _stop_well_formed(seen, session_id):
            return None
        if chain and seen["reentry"] != chain[-1]["reentry"] - 1:
            return None
        chain.append(seen)
        if seen["reentry"] == 0 or seen.get("anchor") is True:
            return chain
    return None


def _stop_append(path, lines, record):
    """Append one record, keeping the last `SESSION_MAX_ENTRIES`; whether it landed."""
    line = json.dumps(record, sort_keys=True)
    if not stop_ledger_safe(path):
        return False
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if len(lines) < SESSION_MAX_ENTRIES and (not path.exists() or path.stat().st_size < SESSION_TRIM_BYTES):
            flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
            with os.fdopen(os.open(path, flags, 0o644), "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        else:
            scratch = path.with_name("%s.%d.tmp" % (path.name, os.getpid()))
            scratch.write_text("\n".join([*lines[-(SESSION_MAX_ENTRIES - 1) :], line]) + "\n", encoding="utf-8")
            scratch.replace(path)
        _prune_old(path.parent)
    except OSError:
        return False
    return True


def _stop_gate_log(root, policy, verdict, reentry, findings):
    """One gate-log record per re-entry; a warn is held (`would_block`), so it is kept even with the log off.

    `reentry` is (index, reentry_verdict, findings_changed or None).
    """
    try:
        if not stop_ledger_safe(Path(root).joinpath(*GATE_LOG_PARTS)):
            return
        held = verdict == STOP_LOG_WARN
        if os.environ.get(GATE_LOG_ENV) == "0" and not held:
            return
        index, reentry_verdict, changed = reentry
        record = {
            "policy_id": policy,
            "surface": "stop-reentry",
            "event": "stop",
            "kind": "reentry",
            "reentry": index,
            "verdict": verdict,
            "reentry_verdict": reentry_verdict,
            "match_count": len(findings),
            "matches": [],
        }
        if held:
            record.update({"would_action": STOP_LOG_BLOCK, "would_block": True})
        if changed is not None:
            record["findings_changed"] = changed
        append_gate_log(Path(root).joinpath(SESSION_STATE_PARTS[0]), record)
    except Exception:  # noqa: BLE001 -- a log must never change what the hook decides
        return


def _stop_warn(policy, why, changed, message):
    """The warning a turn ends with: said on stderr for every client, and returned for a `systemMessage`."""
    text = _STOP_WARNING.format(policy=policy, why=why.format(cap=REENTRY_CAP) + _STOP_SINCE.get(changed, ""))
    text += message
    with contextlib.suppress(Exception):  # stderr may be closed; the warning still goes out as the decision
        sys.stderr.write(text + "\n")
        sys.stderr.flush()
    return VERDICT_WARN, text


def _stop_changed(chain, findings):
    """Whether the findings differ from the last refusal's; None when there is no refusal to compare with."""
    refused = next((r for r in chain or () if r.get("verdict") == STOP_LOG_BLOCK), None)
    if refused is None or not isinstance(refused.get("findings"), list):
        return None
    return sorted(refused["findings"]) != findings


def settle_stop(event, root, gate, decision, writes=None):
    """The decision a Stop earns once this turn's earlier Stops are weighed against `decision`."""
    if decision is not None and decision[0] != VERDICT_DENY:
        return decision
    policy = gate.parent.parent.name
    session_id = session_id_of(event)
    path = stop_ledger_path(root, session_id)
    lines = _stop_lines(path)
    message = decision[1] if decision else ""
    findings = finding_digests(message, writes or {})
    record = {
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "session_id": session_id,
        "phase": STOP_PHASE,
        "policy": policy,
        "turn": _stop_turn(event),
        "findings": findings,
    }
    signalled = reentries(event)
    if not signalled:
        _stop_append(path, lines, {**record, "reentry": 0, "verdict": STOP_LOG_BLOCK if decision else STOP_LOG_ALLOW})
        return decision
    chain = _stop_chain(lines, session_id, policy, record["turn"])
    counted = isinstance(event.raw, dict) and STOP_COUNT_KEY in event.raw
    # A client that counts is believed over the ledger, which an agent can edit.
    index = signalled if counted else (chain[0]["reentry"] + 1 if chain else 1)
    capped = index > REENTRY_CAP
    verdict = STOP_LOG_ALLOW if not decision else (STOP_LOG_WARN if capped else STOP_LOG_BLOCK)
    landed = _stop_append(path, lines, {**record, "reentry": index, "verdict": verdict, "anchor": chain is None})
    changed = _stop_changed(chain, findings)
    if decision is None:
        _stop_gate_log(root, policy, verdict, (index, REENTRY_CLEAN, None), findings)
        return None
    if capped:
        _stop_gate_log(root, policy, verdict, (index, REENTRY_CAPPED, changed), findings)
        return _stop_warn(policy, _STOP_WHY[REENTRY_CAPPED], changed, message)
    if not landed and not counted:
        # `stop_hook_active` says this turn was refused once already; with nowhere to count, a refusal
        # now could never end, so the turn ends here, loudly.
        _stop_gate_log(root, policy, STOP_LOG_WARN, (index, REENTRY_UNTRACKED, None), findings)
        return _stop_warn(policy, _STOP_WHY[REENTRY_UNTRACKED], None, message)
    tracked = REENTRY_REFUSED if chain and landed else REENTRY_UNTRACKED
    _stop_gate_log(root, policy, verdict, (index, tracked, changed), findings)
    return VERDICT_DENY, message + (_STOP_LAST.format(cap=REENTRY_CAP) if index == REENTRY_CAP else "")
