"""One hook process, many policies: a pinned index of members, each judged in its own thread under its own deadline."""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import sys
import threading
import time
from pathlib import Path

from .budget import MEMBER_DEADLINE
from .gate_outcome import VERDICT_WARN
from .guard_runner import VERDICT_DENY, VERDICT_ESCALATE

MULTI_FLAG = "--multi"
INDEX_SHA_FLAG = "--index-sha256"
MEMBER_DEFAULT_SECONDS = 30
_MEMBER_SEPARATOR = "\n"


def multi_from_argv(argv):
    """(index path, pinned sha256) when the hook command names an index, else None."""
    if MULTI_FLAG not in argv:
        return None
    path = argv[argv.index(MULTI_FLAG) + 1] if argv.index(MULTI_FLAG) + 1 < len(argv) else ""
    pin = (
        argv[argv.index(INDEX_SHA_FLAG) + 1]
        if INDEX_SHA_FLAG in argv and argv.index(INDEX_SHA_FLAG) + 1 < len(argv)
        else ""
    )
    return path, pin


def _sha256_of(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_index(path, pin, root):
    """(members, None) when the index matches its pin and every member's files match theirs; else (None, why)."""
    try:
        if not pin or _sha256_of(path) != pin:
            return None, f"the policy index {path} does not match the hash the hook pins"
        members = json.loads(Path(path).read_text(encoding="utf-8"))["members"]
        for member in members:
            for relative, expected in member["files"].items():
                if _sha256_of(Path(root) / relative) != expected:
                    return None, f"{relative} does not match the hash the policy index pins"
            if not isinstance(member["argv"], list) or not float(member.get("timeout", MEMBER_DEFAULT_SECONDS)) > 0:
                return None, "the policy index holds a member chock cannot read"
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        return None, f"the policy index {path} cannot be read ({type(exc).__name__})"
    return members, None


def _fault(member, exc):
    return (
        VERDICT_DENY,
        f"chock could not check this call with {member_name(member)} ({type(exc).__name__}: {exc}). "
        "Refusing rather than reporting an allow it never established.",
    )


def member_name(member):
    """A member's policy, as its argv names it (the file after its first flag)."""
    return next((arg for arg in member["argv"][1:2]), "a policy")


def _member_thread(member, judge_one, slot):
    MEMBER_DEADLINE.set(time.monotonic() + float(member.get("timeout", MEMBER_DEFAULT_SECONDS)))
    try:
        slot["verdict"] = judge_one(member["argv"])
    except Exception as exc:  # noqa: BLE001 -- a crashing member refuses its own call, never the others'
        slot["verdict"] = _fault(member, exc)
    slot["done"] = True


def run_members(members, judge_one):
    """Each member's verdict (or None), in index order. A member past its own deadline refuses its own call."""
    started = time.monotonic()
    running = []
    for member in members:
        slot = {"done": False, "verdict": None}
        thread = threading.Thread(target=_member_thread, args=(member, judge_one, slot), daemon=True)
        thread.start()
        running.append((member, thread, slot))
    verdicts = []
    for member, thread, slot in running:
        allowed = float(member.get("timeout", MEMBER_DEFAULT_SECONDS))
        thread.join(max(started + allowed - time.monotonic(), 0.0))
        if slot["done"]:
            verdicts.append(slot["verdict"])
        else:
            verdicts.append(
                (VERDICT_DENY, f"{member_name(member)} gave no verdict within {allowed:g}s, so it refuses this call.")
            )
    return verdicts


def combine(verdicts):
    """One verdict from many, in index order: any deny wins, then any ask, then the warns; None when all allow."""
    for outcome in (VERDICT_DENY, VERDICT_ESCALATE, VERDICT_WARN):
        reasons = [
            reason for verdict in verdicts if verdict is not None for kind, reason in [verdict] if kind == outcome
        ]
        if reasons:
            return outcome, _MEMBER_SEPARATOR.join(reasons)
    return None


def flush_and_exit(code):
    """Write what was said, then leave without waiting for a member thread that is still running."""
    for stream in (sys.stdout, sys.stderr):
        with contextlib.suppress(OSError, ValueError):
            stream.flush()
    os._exit(code)
