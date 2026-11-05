"""One hook process, many policies: a pinned index of members, each judged in its own thread under its own deadline."""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import sys
import threading
import time
from pathlib import Path, PurePosixPath, PureWindowsPath

from .budget import MEMBER_DEADLINE, kill_live_trees
from .gate_outcome import VERDICT_WARN
from .guard_runner import VERDICT_DENY, VERDICT_ESCALATE

MULTI_FLAG = "--multi"
INDEX_SHA_FLAG = "--index-sha256"
ROOT_FLAG = "--root"
OFF_FLAG = "--off"
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


def root_from_argv(argv):
    """The plugin root a hook command names with `--root`, "" when the flag has no value, None when it is absent."""
    if ROOT_FLAG not in argv:
        return None
    at = argv.index(ROOT_FLAG) + 1
    return argv[at] if at < len(argv) else ""


def off_from_argv(argv):
    """The bundle members a toggle wrapper switched off for this call (`--off a,b`), as a set of ids."""
    at = argv.index(OFF_FLAG) + 1 if OFF_FLAG in argv else len(argv)
    return {name for name in (argv[at] if at < len(argv) else "").split(",") if name}


def sha256_of(path):
    """The sha256 of a file's bytes with CRLF read as LF, so a checkout that converted line endings still matches."""
    return hashlib.sha256(Path(path).read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def _escapes(path):
    """True for a path that is absolute, drive- or root-qualified, or climbs out of the root by a `..` part, on either flavour."""
    return any(
        flavour(path).is_absolute() or ".." in flavour(path).parts or flavour(path).drive or flavour(path).root
        for flavour in (PurePosixPath, PureWindowsPath)
    )


def _member_fault(member, root):
    """Why one index member cannot be trusted (an escaping path, a file off its pin, an unreadable shape), else None."""
    named = [*member["files"], *(a for a in member["argv"] if isinstance(a, str) and not a.startswith("-"))]
    for relative in named:
        if not isinstance(relative, str) or _escapes(relative):
            return f"the policy index names {relative!r}, which is outside the repository root"
    for relative, expected in member["files"].items():
        if sha256_of(Path(root) / relative) != expected:
            return f"{relative} does not match the hash the policy index pins"
    if not isinstance(member["argv"], list) or not float(member.get("timeout", MEMBER_DEFAULT_SECONDS)) > 0:
        return "the policy index holds a member chock cannot read"
    return None


def _rooted(member, root):
    """`member` with each path its argv names joined to `root`: a plugin's members are paths relative to its root."""
    argv = [a if not isinstance(a, str) or a.startswith("-") else str(Path(root) / a) for a in member["argv"]]
    return {**member, "argv": argv}


def load_index(path, pin, root, *, rooted=False):
    """(members, None) when the index matches its pin and every member's files match theirs; else (None, why).

    `root` is where the member paths resolve; `rooted` (a plugin's `--root`) also joins it to each argv path.
    """
    try:
        if not root:
            return None, "the hook command names an empty plugin root, so its policy index cannot be checked"
        if not pin or sha256_of(path) != pin:
            return None, f"the policy index {path} does not match the hash the hook pins"
        members = json.loads(Path(path).read_text(encoding="utf-8"))["members"]
        if not isinstance(members, list) or not members:
            return None, f"the policy index {path} lists no policies, which is a build fault, never an allow"
        for member in members:
            why = _member_fault(member, root)
            if why:
                return None, why
        if rooted:
            members = [_rooted(member, root) for member in members]
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
    except (Exception, SystemExit) as exc:  # noqa: BLE001 -- a crashing member, even a SystemExit, refuses its own call at once
        slot["verdict"] = _fault(member, exc)
    slot["done"] = True


def settle(verdict, *, can_ask=True, warn_speaks=True):
    """One member's verdict as the client can honour it: an ask the client ignores is a deny, a warn it never shows is nothing."""
    if verdict is None:
        return None
    kind, reason = verdict
    if kind == VERDICT_ESCALATE and not can_ask:
        return VERDICT_DENY, reason
    if kind == VERDICT_WARN and not warn_speaks:
        return None
    return verdict


def run_members(members, judge_one, *, can_ask=True, warn_speaks=True, said=None):
    """Each member's settled verdict (or None), in index order. A member past its own deadline refuses its own call.

    The members share this process's streams, so they get none: stdin is empty and what they print on stdout is
    dropped. What they write to stderr (a stop's warning, a note that a worktree went unchecked) is appended to `said`.
    """
    started = time.monotonic()
    saved = sys.stdin, sys.stdout, sys.stderr
    sys.stdin, sys.stdout, sys.stderr = io.StringIO(""), io.StringIO(), io.StringIO()
    try:
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
                verdicts.append(settle(slot["verdict"], can_ask=can_ask, warn_speaks=warn_speaks))
            else:
                verdicts.append(
                    (
                        VERDICT_DENY,
                        f"{member_name(member)} gave no verdict within {allowed:g}s, so it refuses this call.",
                    )
                )
    finally:
        written = sys.stderr.getvalue() if isinstance(sys.stderr, io.StringIO) else ""
        sys.stdin, sys.stdout, sys.stderr = saved
        if said is not None and written:
            said.append(written)
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
    """End every child tree a member left running, write what was said, then leave without waiting for its thread."""
    kill_live_trees()
    for stream in (sys.stdout, sys.stderr):
        with contextlib.suppress(OSError, ValueError):
            stream.flush()
    os._exit(code)
