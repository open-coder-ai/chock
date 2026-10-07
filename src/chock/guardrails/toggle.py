"""The guardrails toggle file and its lookup. Stdlib only: shipped verbatim in every merged plugin as its hook wrapper.

`.chock/guardrails.json` (repo scope, committed) or `~/.chock/guardrails.json` (user scope):
`{"version": 1, "bundles": {"<bundle.name>": {"<policy-id>": "on" | "off"}}}`. An absent entry is on.
A repository's own file governs it; the user file governs only where the repository carries none.
A file that cannot be read or is invalid switches nothing off: every member stays on, with a warning.

As the hook wrapper: `chock_bundle.py --bundle <name> --member <id> <adapter> [adapter args...]`. On runs the
adapter with its args; off runs it with none, so the client still gets its own allow, plus one log line.

`chock bundle on|off` records each file's sha256 in `.chock/state/guardrails.sha256` beside it. As the turn-end
check, `chock_bundle.py --verify <adapter>` refuses a Stop while a toggle file differs from that record: it was
changed outside `chock bundle`. The lookup honours a file only while it matches that record: otherwise all on.
"""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import os
import re
import runpy
import sys
from datetime import datetime, timezone
from pathlib import Path

FILENAME = ".chock/guardrails.json"
VERSION = 1
ON, OFF = "on", "off"
STATES = (ON, OFF)
NAME_RE = re.compile(r"^[a-z][a-z0-9-]{2,63}$")
REPO, USER = "repo", "user"
_TOP_KEYS = frozenset({"version", "bundles"})
_LOG_PARTS, _LOG_ROTATED, _LOG_MAX_BYTES = ("log", "gate-events.jsonl"), "gate-events.1.jsonl", 1_048_576
_GATE_LOG_ENV = "CHOCK_GATE_LOG"
_ARGC = 5
#: The record `chock bundle` keeps of the file it last wrote, beside it under the engine's own state folder.
RECORD_PARTS = ("state", "guardrails.sha256")
VERIFY = "--verify"
DRIFTED = (
    "guardrails.json differs from the last `chock bundle` change; every guardrail stays on until the person "
    "re-applies it or runs `chock bundle status --adopt`"
)
_VERDICT_DENY = "deny"
_BLOCKING_EXIT = 2  # the launcher's refusal too: the wrapper speaks no client's dialect


class ToggleError(ValueError):
    """A toggle file that does not say, unambiguously, which members are off."""


def user_path() -> Path:
    """The user-scope toggle file."""
    return Path.home() / FILENAME


def repo_root(start: Path) -> Path | None:
    """The repository `start` is in: the nearest folder holding `.git`, or None outside one."""
    here = Path(start).absolute()
    for folder in (here, *here.parents):
        if (folder / ".git").exists():
            return folder
    return None


def source(start: Path) -> tuple[Path | None, str | None]:
    """(the file that governs at `start`, its scope); a broken link or a folder governs too, read as all on."""
    root = repo_root(start)
    if root is not None and os.path.lexists(root / FILENAME):
        return root / FILENAME, REPO
    user = user_path()
    return (user, USER) if os.path.lexists(user) else (None, None)


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


def log_off(governing: Path, bundle: str, member: str) -> None:
    """One line in chock's log beside the governing file. Best effort: never raises."""
    try:
        if os.environ.get(_GATE_LOG_ENV) == "0":
            return
        log = governing.parent.joinpath(*_LOG_PARTS)
        log.parent.mkdir(parents=True, exist_ok=True)
        if log.exists() and log.stat().st_size > _LOG_MAX_BYTES:
            log.replace(log.parent / _LOG_ROTATED)
        record = {"ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "policy_id": member}
        record |= {"surface": "plugin", "event": "toggle", "kind": "guardrails-off", "bundle": bundle, "verdict": OFF}
        with log.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")
    except Exception:  # noqa: BLE001 -- a log line must never change the verdict
        return


def _where(payload: bytes) -> Path:
    """The folder the agent works in: the payload's `cwd` (or first workspace root; Cursor's `/C:/x` is `C:/x`)."""
    try:
        raw = json.loads(payload.decode("utf-8-sig"))
        roots = raw.get("workspace_roots") or [None]
        cwd = raw.get("cwd") or roots[0]
        if isinstance(cwd, str) and cwd:
            return Path(cwd[1:] if cwd[:1] == "/" and cwd[2:3] == ":" and cwd[1:2].isalpha() else cwd)
    except Exception:  # noqa: BLE001,S110 -- an unreadable payload is the adapter's to refuse
        pass
    return Path.cwd()


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
        return "it was deleted after `chock bundle` wrote it"
    if then is None:
        return "`chock bundle` has no record of it"
    return "it was changed outside `chock bundle`"


def scopes(start: Path) -> list[Path]:
    """Every toggle file that can govern work at `start`: the repository's, then the user's."""
    root = repo_root(start)
    return [*([root / FILENAME] if root else []), user_path()]


def drifted(start: Path) -> list[str]:
    """One line per toggle file in scope that differs from its record."""
    return [f"{path}: {why}" for path in scopes(start) if (why := drift(path))]


def refusal(lines: list[str]) -> str:
    return (
        "chock: a guardrails toggle file was changed outside `chock bundle`: "
        + "; ".join(lines)
        + ". Only a person changes it: they re-apply it with `chock bundle on|off <policy-id>`, or review it and run"
        " `chock bundle status --adopt`. The agent does not."
    )


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
    """Turn-end check: the adapter answers in its client's own words, refusing a Stop while a toggle file drifted.

    `argv` is the adapter and its own `--gate <gate> --stop`, which still decide how an unreadable payload is refused.
    """
    adapter_path, gate = argv[0], Path(argv[argv.index("--gate") + 1])
    adapter = _adapter(adapter_path)
    where = _where(payload)

    def handle(event):
        if getattr(event, "event", "") != "stop":
            return None
        lines = drifted(where)
        if not lines:
            return None
        settled = adapter.settle_stop(event, repo_root(where) or where, gate, (_VERDICT_DENY, refusal(lines)), {})
        return adapter._spoken(settled) if settled else None

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
        governing, _scope, toggles, warning = load(_where(payload))
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
        sys.argv = wrapped(sys.argv[1:], payload)
        runpy.run_path(sys.argv[0], run_name="__main__")
    except (Exception, SystemExit) as exc:  # the adapter answers its own faults; these never answered
        if isinstance(exc, SystemExit) and isinstance(exc.code, (int, type(None))):
            raise
        sys.stderr.write(f"chock: the guardrails wrapper failed ({type(exc).__name__}: {exc}), so it refuses.\n")
        sys.exit(_BLOCKING_EXIT)


if __name__ == "__main__":
    main()
