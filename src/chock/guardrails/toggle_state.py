"""The toggle file's format and a session's binding to the files it saw. Stdlib only: shipped beside the wrapper."""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import time
from pathlib import Path

VERSION = 1
ON, OFF = "on", "off"
STATES = (ON, OFF)
NAME_RE = re.compile(r"^[a-z][a-z0-9-]{2,63}$")
_TOP_KEYS = frozenset({"version", "bundles"})
#: The session log's id keys (`session_id`, Copilot's `sessionId`), then the conversation id Cursor and Antigravity send instead.
SESSION_ID_KEYS = ("session_id", "sessionId", "conversation_id", "conversationId")
SESSION_ID_MAX = 128
SESSION_UNKNOWN = "unknown"
BOUND_NAME = "guardrails-session-{}.json"
BOUND_PRUNE_SECONDS = 7 * 24 * 3600
UNSEEN = [None, None]
#: The built-in self-protection: never a catalog member, so an entry naming it switches nothing.
PROTECT_ID = "chock-guardrails-protect"
DELETED = "it was deleted after `chock bundle` wrote it"
DRIFTED = (
    "guardrails.json differs from the last `chock bundle` change; every guardrail stays on until the person "
    "re-applies it or runs `chock bundle status --adopt`"
)
#: The record `chock bundle` keeps of the file it last wrote, beside it under the engine's own state folder.
RECORD_PARTS = ("state", "guardrails.sha256")


class ToggleError(ValueError):
    """A toggle file that does not say, unambiguously, which members are off."""


def _require_object(value: object, where: str) -> dict:
    if not isinstance(value, dict):
        msg = f"{where} must be an object, got {type(value).__name__}"
        raise ToggleError(msg)
    return value


def parse(text: str) -> dict[str, dict[str, str]]:
    """{bundle: {policy id: on|off}} from the file's text, or ToggleError saying what is wrong."""
    try:
        document = json.loads(text)
    except ValueError as exc:
        msg = f"not valid JSON ({exc})"
        raise ToggleError(msg) from exc
    _require_object(document, "the file")
    if set(document) != _TOP_KEYS:
        msg = f"the file must have exactly the keys {sorted(_TOP_KEYS)}, got {sorted(document)}"
        raise ToggleError(msg)
    version = document["version"]
    if type(version) is not int or version != VERSION:
        msg = f"version must be {VERSION}, got {version!r}"
        raise ToggleError(msg)
    bundles: dict[str, dict[str, str]] = {}
    for name, members in _require_object(document["bundles"], "'bundles'").items():
        if not NAME_RE.fullmatch(name):
            msg = f"bundle name {name!r} must match {NAME_RE.pattern}"
            raise ToggleError(msg)
        for policy_id, state in _require_object(members, f"bundle {name!r}").items():
            if not NAME_RE.fullmatch(policy_id):
                msg = f"policy id {policy_id!r} in {name!r} must match {NAME_RE.pattern}"
                raise ToggleError(msg)
            if state not in STATES:
                msg = f"{name}/{policy_id} is {state!r}; a state is 'on' or 'off', never a pattern or a rule"
                raise ToggleError(msg)
        bundles[name] = dict(members)
    return bundles


def read(path: Path) -> dict[str, dict[str, str]]:
    """The parsed file at `path`; ToggleError for anything unreadable, so it reads as all on."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        msg = f"cannot be read ({type(exc).__name__})"
        raise ToggleError(msg) from exc
    return parse(text)


def document(payload: bytes) -> dict:
    """The hook payload as an object; empty when it is not one."""
    try:
        raw = json.loads(payload.decode("utf-8-sig"))
    except ValueError:
        return {}
    return raw if isinstance(raw, dict) else {}


def session_id(payload: bytes) -> str:
    """The session's id as the session log names it: a safe file stem, never empty."""
    raw = document(payload)
    given = next((raw[key] for key in SESSION_ID_KEYS if raw.get(key)), "")
    stem = "".join(c for c in str(given) if c.isalnum() or c in "._-").lstrip(".")
    return stem[:SESSION_ID_MAX] or SESSION_UNKNOWN


def keep(path: Path, states: dict[str, list], *, replace: bool) -> None:
    """Write the binding whole or not at all; without `replace`, an existing one wins. Best effort: never raises."""
    scratch = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        scratch.write_text(json.dumps(states), encoding="utf-8")
        if replace:
            os.replace(scratch, path)
            cutoff = time.time() - BOUND_PRUNE_SECONDS
            for old in path.parent.glob(BOUND_NAME.format("*")):
                if old.stat().st_mtime < cutoff:
                    old.unlink()
        else:
            os.link(scratch, path)
    except OSError:  # no binding is kept: the session then reads every file as changed
        pass
    finally:
        with contextlib.suppress(OSError):
            scratch.unlink()


def bind(folder: Path, states: dict[str, list], session: str, *, fresh: bool) -> dict | None:
    """The files' states this session is bound to in `folder`, or None when it is bound to none.

    A session start (`fresh`) binds anew. Any other first hook binds the session to what it sees, an absent file
    included, when the client names the session; one that does not stays unbound until a session start.
    """
    path = folder / BOUND_NAME.format(session)
    if fresh or (session != SESSION_UNKNOWN and not path.exists()):
        keep(path, states, replace=fresh)
    try:
        bound = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return bound if isinstance(bound, dict) else None


def moved(states: dict[str, list], bound: dict | None) -> list[Path]:
    """Every file in `states` whose state is not the one the session was bound to (an unbound file always is)."""
    held = bound or {}
    return [Path(file) for file, state in states.items() if held.get(file, UNSEEN) != state]


def record_path(toggle_file: Path) -> Path:
    """Where `chock bundle` records the sha256 of the toggle file it wrote."""
    return Path(toggle_file).parent.joinpath(*RECORD_PARTS)


def digest(path: Path) -> str | None:
    """The sha256 of a file's bytes; None when nothing is there, `unreadable` when something is but cannot be read."""
    if not os.path.lexists(path):
        return None
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return "unreadable"


def recorded(toggle_file: Path) -> str | None:
    """The sha256 `chock bundle` last recorded for `toggle_file`, or None when it recorded none."""
    try:
        return record_path(toggle_file).read_text(encoding="utf-8").strip() or None
    except (OSError, UnicodeDecodeError):
        return None


def drift(toggle_file: Path) -> str | None:
    """Why `toggle_file` is not what `chock bundle` last wrote, or None when it is (or neither exists)."""
    now, then = digest(toggle_file), recorded(toggle_file)
    if now == then:
        return None
    if now is None:
        return DELETED
    return "`chock bundle` has no record of it" if then is None else "it was changed outside `chock bundle`"


def has_off(path: Path) -> bool:
    """Whether the file at `path` switches any member off."""
    try:
        return any(state == OFF for members in read(path).values() for state in members.values())
    except ToggleError:
        return False


def listed_off(paths: list[Path], governing: Path | None, user: Path) -> list[str]:
    """One line per recorded file in `paths` that switches a member off; `governing` is the file that applies here."""
    lines = []
    for path in paths:
        if not os.path.lexists(path) or drift(path):
            continue
        try:
            off = sorted(
                f"{b}/{i}" for b, ms in read(path).items() for i, s in ms.items() if s == OFF and i != PROTECT_ID
            )
        except ToggleError:
            continue
        if off:
            shadowed = "" if governing in (None, path) else " (not applied here: the repository's own file governs)"
            lines.append(f"{'user' if path == user else 'repo'} ({path}){shadowed}: {', '.join(off)}")
    return lines
