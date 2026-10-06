"""The guardrails toggle file and its lookup. Stdlib only: shipped verbatim in every merged plugin as its hook wrapper.

`.chock/guardrails.json` (repo scope, committed) or `~/.chock/guardrails.json` (user scope):
`{"version": 1, "bundles": {"<bundle.name>": {"<policy-id>": "on" | "off"}}}`. An absent entry is on.
A repository's own file governs it; the user file governs only where the repository carries none.
A file that cannot be read or is invalid switches nothing off: every member stays on, with a warning.

As the hook wrapper: `chock_bundle.py --bundle <name> --member <id> <adapter> [adapter args...]`. On runs the
adapter with its args; off runs it with none, so the client still gets its own allow, plus one log line.
"""

from __future__ import annotations

import io
import json
import os
import re
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
_LOG_PARTS = ("log", "gate-events.jsonl")
_LOG_ROTATED = "gate-events.1.jsonl"
_LOG_MAX_BYTES = 1_048_576
_GATE_LOG_ENV = "CHOCK_GATE_LOG"
_ARGC = 5


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


def _present(path: Path) -> bool:
    """Whether anything is at `path`: a broken link or a folder governs too, and reads as all on."""
    return os.path.lexists(path)


def source(start: Path) -> tuple[Path | None, str | None]:
    """(the file that governs at `start`, its scope); (None, None) when neither file exists."""
    root = repo_root(start)
    if root is not None and _present(root / FILENAME):
        return root / FILENAME, REPO
    user = user_path()
    return (user, USER) if _present(user) else (None, None)


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
        record = {
            "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "policy_id": member,
            "surface": "plugin",
            "event": "toggle",
            "kind": "guardrails-off",
            "bundle": bundle,
            "verdict": OFF,
        }
        with log.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")
    except Exception:  # noqa: BLE001 -- a log line must never change the verdict
        return


def _where(payload: bytes) -> Path:
    """The folder the agent works in: the payload's `cwd` (or first workspace root), else this process's."""
    try:
        raw = json.loads(payload.decode("utf-8-sig"))
        roots = raw.get("workspace_roots") or [None]
        cwd = raw.get("cwd") or roots[0]
        if isinstance(cwd, str) and cwd:
            return Path(cwd)
    except Exception:  # noqa: BLE001,S110 -- an unreadable payload is the adapter's to refuse
        pass
    return Path.cwd()


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
    payload = sys.stdin.buffer.read()
    sys.argv = wrapped(sys.argv[1:], payload)
    sys.stdin = io.TextIOWrapper(io.BytesIO(payload), encoding="utf-8")
    adapter = Path(sys.argv[0])
    code = compile(adapter.read_bytes(), str(adapter), "exec")
    exec(code, {"__name__": "__main__", "__file__": str(adapter), "__builtins__": __builtins__})  # noqa: S102 -- the client's own shipped adapter, run as `python <adapter>` would


if __name__ == "__main__":
    main()
