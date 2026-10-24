"""Gate runner: the decision log's level, settings, redaction and writer. Stdlib only; gate.py and every runtime carry it."""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from .chain import (
    LOG_CHAIN_KEYS,
    LOG_CHAIN_UNCHAINED,
    LOG_OPEN_FLAGS,
    log_chain_after,
    log_last_line,
    log_require_safe,
    log_rotated,
    log_tail,
)

# >>> gate.py 20
#: The level a person set for this shell's hooks; an agent's tool input never reaches a hook's environment.
LOG_LEVEL_ENV = "CHOCK_LOG_LEVEL"
#: Deprecated: `CHOCK_GATE_LOG=0` reads as `CHOCK_LOG_LEVEL=off`.
LOG_LEGACY_ENV = "CHOCK_GATE_LOG"
LOG_OFF, LOG_INFO, LOG_DEBUG = "off", "info", "debug"
LOG_LEVELS = (LOG_OFF, LOG_INFO, LOG_DEBUG)
#: One settings file per scope: `<repo>/.chock/chock-log.json`, then `~/.chock/chock-log.json`. A person edits it.
LOG_SETTINGS_PARTS = (".chock", "chock-log.json")
LOG_SETTINGS_KEYS = ("level", "max_bytes")
LOG_DEFAULT_MAX_BYTES = 1_048_576
LOG_MIN_MAX_BYTES = 65_536
LOG_MAX_MAX_BYTES = 1_073_741_824
LOG_ALLOW = "allow"
#: Fields that make an allow a decision worth an info line: something let a policy's finding through,
#: or an agent's action, kept as its fingerprint (`target`) so the log can say what the agent touched.
LOG_LET_THROUGH = ("override", "would_action", "target")
#: A debug trace's command or path is cut to this many characters, after redaction.
LOG_TRACE_CAP = 200
LOG_REDACTED = "[redacted]"
#: The client's id for one tool call (`tool_use_id`): what lets every hook judging it log its plain allow once.
LOG_CALL = "call"
#: Beside the log, one empty file per tool call already logged: whichever hook creates it writes the line.
LOG_CLAIMS = ".calls"
#: A plain allowed tool call's one line is the call's, never one policy's: these fields of its hook are left out.
_LOG_PER_HOOK = ("policy_id", "plugin", "plugin_version", "kind", "match_count", "matches", "rules")
#: A claim outlives every hook of its call (each runs within its client's timeout), then is pruned.
LOG_CLAIM_SECONDS = 600
#: A claim whose name starts with this prunes the old ones: about one claim in 16.
_LOG_CLAIM_PRUNER = "0"
_LOG_CLAIM_NAME = 32
#: A lone surrogate (a path that was not UTF-8) cannot be encoded: it is written as the text `\uXXXX`.
_LOG_SURROGATE = re.compile("[\ud800-\udfff]")
#: The scan-secrets policy's content_pattern, vendored: a debug trace never carries a value it would block.
_LOG_SECRET_RE = re.compile(
    r"""(?i)((AKIA|ASIA)[0-9A-Z]{16}|gh[oprsu]_[0-9A-Za-z]{36}|github_pat_[0-9A-Za-z_]{22,}|xox[bpas]-[0-9A-Za-z-]{10,}|(sk|rk)_live_[0-9A-Za-z]{16,}|sk-proj-[0-9A-Za-z_-]{20,}|sk-ant-[0-9A-Za-z_-]{20,}|sk-[0-9A-Za-z]{20,}|AIza[0-9A-Za-z_-]{35}|npm_[0-9A-Za-z]{36}|SG\.[0-9A-Za-z_-]{16,}\.[0-9A-Za-z_-]{16,}|eyJ[A-Za-z0-9_-]*\.[A-Za-z0-9_-]*\.[A-Za-z0-9_-]*|-----BEGIN (RSA |OPENSSH |EC |DSA )?PRIVATE KEY-----|api[_-]?key\s*=\s*["'][A-Za-z0-9_\-]{20,}["']|secret[_-]?key\s*=\s*["'][A-Za-z0-9_\-]{20,}["']|auth[_-]?token\s*=\s*["'][A-Za-z0-9_\-]{20,}["']|password\s*=\s*["'][^"'\s]{12,}["']|(api|secret|auth)[_-]?(key|token)\s*[=:]\s*[A-Za-z0-9_\-]{20,}|password\s*[=:]\s*[^\s"'${}]{12,})"""
)
_LOG_BYTES_RANGE = "a whole number from 65536 (64 KiB) to 1073741824 (1 GiB)"
#: How long a writer waits for the chain's lock before it writes its line unchained; held for one read and one write.
LOG_CHAIN_WAIT = 1.0
_LOG_CHAIN_POLL = 0.0002


def log_settings_read(path):
    """(the valid settings in one scope's file, what is wrong with it); a missing file is ({}, [])."""
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}, []
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        return {}, [f"{path}: unreadable or not JSON ({exc})"]
    if not isinstance(doc, dict):
        return {}, [f"{path}: must be a JSON object with level and/or max_bytes"]
    found, problems = {}, []
    level, size = doc.get("level"), doc.get("max_bytes")
    if level in LOG_LEVELS:
        found["level"] = level
    elif level is not None:
        problems.append(f"{path}: level must be off, info or debug, not {level!r}")
    if type(size) is int and LOG_MIN_MAX_BYTES <= size <= LOG_MAX_MAX_BYTES:
        found["max_bytes"] = size
    elif size is not None:
        problems.append(f"{path}: max_bytes must be {_LOG_BYTES_RANGE}, not {size!r}; using the next scope or 1048576")
    unknown = sorted(set(doc) - set(LOG_SETTINGS_KEYS))
    if unknown:
        problems.append(f"{path}: unknown key(s) {', '.join(map(str, unknown))}; only level and max_bytes are read")
    return found, problems


def log_settings_paths(repo_root):
    """The settings files in precedence order: the repository's (when known), then the user's."""
    repo = [Path(repo_root).joinpath(*LOG_SETTINGS_PARTS)] if repo_root is not None else []
    return [*repo, Path(os.path.expanduser("~")).joinpath(*LOG_SETTINGS_PARTS)]


def log_env_level():
    """The level the hook's own environment sets, or None: the legacy switch, then `CHOCK_LOG_LEVEL`."""
    if os.environ.get(LOG_LEGACY_ENV) == "0":
        return LOG_OFF
    named = os.environ.get(LOG_LEVEL_ENV, "").strip().lower()
    return named if named in LOG_LEVELS else None


def log_settings(repo_root):
    """(level, max_bytes) in force: the environment, then the repository's file, the user's, then info and 1 MiB."""
    scopes = [log_settings_read(path)[0] for path in log_settings_paths(repo_root)]
    level = log_env_level() or next((s["level"] for s in scopes if "level" in s), LOG_INFO)
    size = next((s["max_bytes"] for s in scopes if "max_bytes" in s), LOG_DEFAULT_MAX_BYTES)
    return level, size


def log_record_level(record):
    """`debug` for a plain allow, `info` for every decision a policy made, something let through, or an agent's action."""
    plain = record.get("verdict") == LOG_ALLOW and not any(key in record for key in LOG_LET_THROUGH)
    return LOG_DEBUG if plain else LOG_INFO


def log_plain_action(record):
    """Whether `record` is an agent's action that every policy let through untouched: one line per tool call."""
    untouched = not any(key in record for key in LOG_LET_THROUGH if key != "target")
    return record.get("verdict") == LOG_ALLOW and "target" in record and untouched


def _log_prune_claims(folder):
    cutoff = datetime.now(timezone.utc).timestamp() - LOG_CLAIM_SECONDS
    for claim in folder.iterdir():
        try:
            if claim.stat().st_mtime < cutoff:
                claim.unlink()
        except OSError:
            continue


def log_claim(path, record, call):
    """True for the first hook to log this tool call's plain allow; False for every later one. Fails open.

    The call is the client's `tool_use_id`, else (session, second, target): identical calls in one second are one.
    """
    key = "\0".join((str(record.get("session_id")), str(record.get("target")), call or log_now()))
    name = hashlib.sha256(key.encode("utf-8", "backslashreplace")).hexdigest()[:_LOG_CLAIM_NAME]
    folder = Path(path).parent / LOG_CLAIMS
    try:
        folder.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.close(os.open(str(folder / name), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600))
    except FileExistsError:
        return False
    except OSError:
        return True  # no claim to be had: a duplicate line beats a lost one
    if name.startswith(_LOG_CLAIM_PRUNER):
        _log_prune_claims(folder)
    return True


def log_now():
    """The UTC time to the second, as every line is stamped."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def log_admits(level, record_level):
    """Whether a record of `record_level` is written at `level`."""
    return level == LOG_DEBUG or (level == LOG_INFO and record_level == LOG_INFO)


def log_redact(text):
    """`text` with every value scan-secrets would block replaced."""
    return _LOG_SECRET_RE.sub(LOG_REDACTED, str(text))


def log_trace_text(text):
    """`text` with every value scan-secrets would block replaced, then cut to `LOG_TRACE_CAP` characters."""
    redacted = log_redact(text)
    return redacted if len(redacted) <= LOG_TRACE_CAP else redacted[:LOG_TRACE_CAP] + "..."


def log_windows():
    """Whether this is Windows, whose lock is msvcrt's rather than fcntl's."""
    return os.name == "nt"


def log_lock(fd):
    """Take a non-blocking exclusive lock on `fd` (msvcrt on Windows, fcntl elsewhere); False when it is held."""
    try:
        if log_windows():
            import msvcrt  # noqa: PLC0415 -- the platform's own lock, imported where it exists

            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        else:
            import fcntl  # noqa: PLC0415 -- the platform's own lock, imported where it exists

            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (OSError, ImportError):
        return False
    return True


def log_unlock(fd):
    """Release `log_lock`'s lock; closing the descriptor releases an fcntl lock on its own."""
    if log_windows():
        try:
            import msvcrt  # noqa: PLC0415 -- the platform's own lock, imported where it exists

            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        except (OSError, ImportError):
            return


def _log_lock_wait(fd):
    """Take `log_lock`'s lock on `fd`, waiting up to `LOG_CHAIN_WAIT` seconds; False when it stays held."""
    deadline = time.monotonic() + LOG_CHAIN_WAIT
    while not log_lock(fd):
        if time.monotonic() >= deadline:
            return False
        time.sleep(_LOG_CHAIN_POLL)
    return True


def _log_rotate_held(path, max_bytes):
    """Move a file past `max_bytes` to `log_rotated(path)`; the caller holds the chain's lock. A failed move waits."""
    try:
        if path.stat().st_size > max_bytes:
            path.replace(log_rotated(path))
    except OSError:
        return


def _log_line(path, stamped, *, held):
    """`stamped` as one line's bytes, chained after the last line (or the rotated file's) when the lock is `held`.

    A line that cannot be chained names why (`unchained`); a torn last line (no newline) is closed, never joined.
    """
    try:
        last, torn = log_tail(path)
        if held:
            stamped = {**stamped, **log_chain_after(last or log_last_line(log_rotated(path)))}
        else:
            stamped = {**stamped, LOG_CHAIN_UNCHAINED: "lock"}
    except (OSError, ValueError):
        torn = False
        stamped = {**stamped, LOG_CHAIN_UNCHAINED: "unreadable" if held else "lock"}
    text = _LOG_SURROGATE.sub(lambda found: f"\\\\u{ord(found[0]):04x}", json.dumps(stamped, ensure_ascii=False))
    line = (text + "\n").encode("utf-8")
    return b"\n" + line if torn else line


def log_append(path, record, max_bytes=LOG_DEFAULT_MAX_BYTES):
    """Append one stamped, chained, complete line to `path` in a single write, under the chain's lock.

    Each line names the sha256 of the line before it (`prev`) and its place (`seq`); the first line after a
    rotation names the rotated file's last. A writer that cannot take the lock writes its line `unchained`.
    """
    path = Path(path)
    log_require_safe(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    stamped = {"ts": log_now(), **{k: v for k, v in record.items() if k not in LOG_CHAIN_KEYS}}
    lock = os.open(str(path) + ".lock", os.O_RDWR | os.O_CREAT | LOG_OPEN_FLAGS, 0o600)
    try:
        held = _log_lock_wait(lock)
        try:
            if held:
                _log_rotate_held(path, max_bytes)
            line = _log_line(path, stamped, held=held)
            fd = os.open(
                str(path), os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_BINARY", 0) | LOG_OPEN_FLAGS, 0o600
            )
            try:
                os.write(fd, line)
            finally:
                os.close(fd)
        finally:
            if held:
                log_unlock(lock)
    finally:
        os.close(lock)


def log_write(path, record, repo_root):
    """Write `record` to `path` when the level in force for `repo_root` admits it, stamped with its level. Raises on I/O.

    A plain allowed action is written once per tool call (`call`, never itself written), by the first hook and
    naming no policy; at debug every later hook still writes its own line.
    """
    level, size = log_settings(repo_root)
    record = dict(record)
    call = record.pop(LOG_CALL, None)
    record_level = log_record_level(record)
    kept = "would_action" in record and os.environ.get(LOG_LEGACY_ENV) == "0"  # the legacy switch kept rollout evidence
    if not (kept or log_admits(level, record_level)):
        return
    if log_plain_action(record):
        if log_claim(path, record, call):
            record = {key: value for key, value in record.items() if key not in _LOG_PER_HOOK}
        elif level == LOG_INFO:
            return
    log_append(path, {**record, "level": record_level}, size)
