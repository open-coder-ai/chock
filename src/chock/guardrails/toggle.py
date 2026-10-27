"""The guardrails toggle file and its lookup. Stdlib only: shipped verbatim in every merged plugin as its hook wrapper.

`.chock/guardrails.json` (repo; else `~/.chock/guardrails.json`) is all on when absent, invalid or unlike its record.
`--bundle <b> --member <id> <adapter> [args...]`: off runs the adapter with no args. `--verify <adapter>`: a Stop is
refused while a toggle file in its `cwd` or any workspace root loosened or changed during the session.
`--session-start <adapter>`: binds the session to the files it sees and lists every member that is off.

An `off` is honoured only by a session that started after its file's record last changed: a session is bound to the
files it first saw (the session log's id names it), and once one differs every member is on for the rest of it. This
is not a security boundary against an agent running as the person: that agent can write both the file and its record.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import runpy
import sys
from pathlib import Path

try:  # beside this wrapper in a merged plugin; inside the chock package everywhere else
    import chock_bundle_state as ts
    from chock_bundle_log import log_off
except ImportError:
    from chock.guardrails import toggle_state as ts
    from chock.guardrails.chock_bundle_log import log_off

DELETED, DRIFTED, PROTECT_ID, ToggleError = ts.DELETED, ts.DRIFTED, ts.PROTECT_ID, ts.ToggleError
NAME_RE, OFF, ON, STATES, VERSION = ts.NAME_RE, ts.OFF, ts.ON, ts.STATES, ts.VERSION
digest, drift, has_off, listed_off, parse, read = ts.digest, ts.drift, ts.has_off, ts.listed_off, ts.parse, ts.read
document, record_path, recorded, session_id = ts.document, ts.record_path, ts.recorded, ts.session_id

FILENAME = ".chock/guardrails.json"
REPO, USER = "repo", "user"
_ARGC = 5
VERIFY = "--verify"
SESSION_START = "--session-start"
SOURCE_COMPACT = "compact"
MOVED = (
    "changed during this session, so an `off` in it applies from the next session; every guardrail stays on until then"
)
_VERDICT_DENY = "deny"
_BLOCKING_EXIT = 2  # the launcher's refusal too: the wrapper speaks no client's dialect
_NOTICE = (
    "chock: these guardrails are switched off for this session (set before it started; `chock bundle status` shows "
    "them):\n{listed}\nA toggle is not a security boundary against an agent running as the person; a change made "
    "during a session applies from the next one."
)


def user_path() -> Path:
    """The user-scope toggle file."""
    return Path.home() / FILENAME


def repo_root(start: Path) -> Path | None:
    """The repository `start` is in: the nearest folder holding `.git`, or None outside one."""
    here = Path(start).absolute()
    return next((folder for folder in (here, *here.parents) if (folder / ".git").exists()), None)


def source(start: Path) -> tuple[Path | None, str | None]:
    """(the file that governs at `start`, its scope); a broken link or a folder governs too, read as all on."""
    root = repo_root(start)
    if root is not None and os.path.lexists(root / FILENAME):
        return root / FILENAME, REPO
    user = user_path()
    return (user, USER) if os.path.lexists(user) else (None, None)


def load(start: Path) -> tuple[Path | None, str | None, dict[str, dict[str, str]], str | None]:
    """(governing file, scope, toggles, warning). An invalid file yields no toggles: all on, plus the warning."""
    path, scope = source(start)
    if path is None:
        return None, None, {}, None
    if drift(path):
        return path, scope, {}, f"{path}: {DRIFTED}"
    try:
        return path, scope, read(path), None
    except ToggleError as exc:
        return path, scope, {}, f"{path} is ignored, every guardrail stays on: {exc}"


def state(toggles: dict[str, dict[str, str]], bundle: str, member: str) -> str:
    """A member's state: off only when its own entry says so."""
    return OFF if toggles.get(bundle, {}).get(member) == OFF else ON


def _wheres(payload: bytes) -> list[Path]:
    """Where the agent works: `cwd` (goose: `working_dir`), then each workspace root (Cursor's `/C:/x` is `C:/x`)."""
    try:
        raw = json.loads(payload.decode("utf-8-sig"))
        roots = [r for k in ("workspace_roots", "workspacePaths") if isinstance(raw.get(k), list) for r in raw[k]]
        named = [raw.get("cwd") or raw.get("working_dir"), *roots]
    except Exception:  # noqa: BLE001 -- an unreadable payload is the adapter's to refuse
        named = []
    folders = [t[1:] if t[:1] == "/" and t[2:3] == ":" and t[1:2].isalpha() else t for t in named if isinstance(t, str)]
    return [Path(folder) for folder in folders if folder] or [Path.cwd()]


def scopes(start: Path) -> list[Path]:
    """Every toggle file that can govern work at `start`: the repository's, then the user's."""
    root = repo_root(start)
    return [*([root / FILENAME] if root else []), user_path()]


def _states(starts: list[Path]) -> dict[str, list]:
    """{toggle file: [sha256 of it, its record]} for every file in scope of any of `starts`."""
    paths = dict.fromkeys(path for start in starts for path in scopes(start))
    return {str(path): [digest(path), recorded(path)] for path in paths}


def bind(starts: list[Path], session: str, *, fresh: bool) -> dict | None:
    """The files' states `session` is bound to in the user's engine state folder, which a `cd` cannot move."""
    return ts.bind(user_path().parent / "state", _states(starts), session, fresh=fresh)


def moved(starts: list[Path], bound: dict | None) -> list[Path]:
    """Every toggle file in scope whose state is not the one the session was bound to."""
    return ts.moved(_states(starts), bound)


def switched_off(starts: list[Path]) -> list[str]:
    """One line per toggle file in scope that switches a member off: its scope, path and members."""
    return listed_off(list(dict.fromkeys(p for s in starts for p in scopes(s))), source(starts[0])[0], user_path())


def handed_to_user() -> str | None:
    """Why a deleted repo file loosens: the user file that now governs switches members off, or is unvouched for."""
    user = user_path()
    if not os.path.lexists(user):
        return None
    if drift(user):
        return f"deleting it hands control to {user}, which `chock bundle` did not write"
    try:
        off = sorted(f"{b}/{i}" for b, members in read(user).items() for i, s in members.items() if s == OFF)
    except ToggleError:
        return None
    return f"deleting it hands control to {user}, which switches {', '.join(off)} off" if off else None


def turn_end_drifted(starts: list[Path], session: str | None = None) -> list[str]:
    """One line per toggle file in scope of any of `starts` that loosened or, in `session`, changed to switch a member off.

    A tightening deletion drops its record.
    """
    lines = []
    for path in dict.fromkeys(path for start in starts for path in scopes(start)):
        why = drift(path)
        if why == DELETED:
            why = None if path == user_path() else handed_to_user()
            if why is None:
                with contextlib.suppress(OSError):
                    record_path(path).unlink()
        if why:
            lines.append(f"{path}: {why}")
    if session is not None:
        listed = {line.split(": ", 1)[0] for line in lines}
        late = [p for p in moved(starts, bind(starts, session, fresh=False)) if has_off(p) and str(p) not in listed]
        lines += [f"{path}: {MOVED}" for path in late]
    return lines


def _adapter(path: str):
    """The client's adapter loaded as a module, its `main` not yet run."""
    spec = importlib.util.spec_from_file_location("chock_adapter", path)
    if spec is None or spec.loader is None:
        msg = f"cannot load the adapter at {path}"
        raise SystemExit(msg)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def verify(argv: list[str], payload: bytes) -> None:
    """Turn-end check: the adapter (`argv`: it, `--gate <gate> --stop`) refuses a Stop while a toggle file drifted."""
    adapter, gate = _adapter(argv[0]), Path(argv[argv.index("--gate") + 1])
    wheres, session = _wheres(payload), session_id(payload)
    ledger = next((root for root in map(repo_root, wheres) if root), wheres[0])
    refuse = adapter.handle  # an entry whose shared runtime failed to load refuses every event itself

    def handle(event):
        if getattr(adapter, "_CHOCK_RUNTIME_FAULT", None) is not None:
            return refuse(event)
        lines = turn_end_drifted(wheres, session) if getattr(event, "event", "") == "stop" else []
        refusal = (
            f"chock: a guardrails toggle file was changed outside `chock bundle` or since this session started: "
            f"{'; '.join(lines)}. Only a person changes it: they re-apply it with `chock bundle on|off <policy-id>`, "
            "or review it and run `chock bundle status --adopt`; an `off` applies from the next session. "
            "The agent does not."
        )
        decision = adapter.settle_stop(event, ledger, gate, (_VERDICT_DENY, refusal), {}) if lines else None
        return adapter._spoken(decision) if decision else None

    adapter.handle = handle
    sys.argv = list(argv)
    adapter.main()


def start(argv: list[str], payload: bytes) -> None:
    """Session start: the adapter (`argv`: it) logs its heartbeat; the session is bound and told what is off."""
    adapter, wheres, session = _adapter(argv[0]), _wheres(payload), session_id(payload)
    heartbeat = adapter.handle
    resumed = document(payload).get("source") != SOURCE_COMPACT  # a compaction continues the session it is in

    def handle(event):
        decision = heartbeat(event)
        if decision is not None or getattr(event, "event", "") != "session_start":
            return decision
        bind(wheres, session, fresh=resumed)
        listed = switched_off(wheres)
        return adapter.Decision.allow(context=_NOTICE.format(listed="\n".join(listed))) if listed else None

    adapter.handle = handle
    sys.argv = list(argv)
    adapter.main()


def wrapped(argv: list[str], payload: bytes) -> list[str]:
    """The adapter argv this member runs with: its own when on, none when off. Any doubt is on."""
    if len(argv) < _ARGC or argv[0] != "--bundle" or argv[2] != "--member":
        msg = "usage: chock_bundle.py --bundle <name> --member <id> <adapter> [args...]"
        raise SystemExit(msg)
    bundle, member, adapter, rest = argv[1], argv[3], argv[4], argv[5:]
    try:
        starts = _wheres(payload)
        governing, _scope, toggles, warning = load(starts[0])
        held = moved(starts, bind(starts, session_id(payload), fresh=False))
        if held and any(s == OFF for members in toggles.values() for s in members.values()):
            toggles, warning = {}, "; ".join(f"{path}: {MOVED}" for path in held)
    except Exception as exc:  # noqa: BLE001 -- a lookup that fails switches nothing off
        governing, toggles, warning = None, {}, f"the guardrails toggle lookup failed, every guardrail stays on: {exc}"
    if warning:
        sys.stderr.write(f"chock: {warning}\n")
    if governing is not None and state(toggles, bundle, member) == OFF:
        log_off(governing, bundle, member)
        return [adapter]
    return [adapter, *rest]


def main() -> None:
    """Hook entry: decide on or off, then run the client's adapter in this process on the same payload."""
    try:
        payload = sys.stdin.buffer.read()
        sys.stdin = io.TextIOWrapper(io.BytesIO(payload), encoding="utf-8")
        if sys.argv[1:2] == [VERIFY]:
            verify(sys.argv[2:], payload)
            return
        if sys.argv[1:2] == [SESSION_START]:
            start(sys.argv[2:], payload)
            return
        sys.argv = wrapped(sys.argv[1:], payload)
        runpy.run_path(sys.argv[0], run_name="__main__")
    except (Exception, SystemExit) as exc:  # the adapter answers its own faults; these never answered
        if isinstance(exc, SystemExit) and isinstance(exc.code, (int, type(None))):
            raise
        sys.stderr.write(f"chock: the guardrails wrapper failed ({type(exc).__name__}: {exc}), so it refuses.\n")
        sys.exit(_BLOCKING_EXIT)


if __name__ == "__main__":
    main()
