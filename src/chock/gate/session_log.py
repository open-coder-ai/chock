"""The per-session tool-call log the vendored runtime appends to. Stdlib only; never imports chock.

One JSON object per line under `.chock/state/<session_id>.jsonl`, local to the machine and
gitignored. A record names the tool and a summary of its input (a path, a command's first line,
a URL without query) and never a file's content or an environment value. Nothing here can change
a verdict: every failure is swallowed.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

SESSION_MAX_ENTRIES = 500
SESSION_PRUNE_SECONDS = 7 * 24 * 3600
SESSION_FIELD_CAP = 300
#: Rewrite (trim) only past this size, so an ordinary append stays a single write.
SESSION_TRIM_BYTES = 131072
#: How many trailing records a new one is compared with, so several policies' hooks log a call once.
SESSION_DEDUPE_TAIL = 8
SESSION_STATE_PARTS = (".chock", "state")
SESSION_INPUT_KEYS = ("tool_input", "toolInput", "toolArgs", "input")
SESSION_PATH_KEYS = ("file_path", "filePath", "path", "notebook_path", "target_file", "TargetFile")
SESSION_URL_KEYS = ("url", "uri")
SESSION_RESPONSE_KEYS = ("tool_response", "toolResponse", "tool_result", "toolResult")
SESSION_UNKNOWN_ID = "unknown"
SESSION_ID_MAX = 128
SESSION_MASK = "***"


def tool_call_input(event):
    """The tool's arguments as a dict, decoding the JSON-string form some vendors send; {} when absent."""
    raw = getattr(event, "raw", None)
    if not isinstance(raw, dict):
        return {}
    for key in SESSION_INPUT_KEYS:
        value = raw.get(key)
        if isinstance(value, str) and value[:1] == "{":
            try:
                value = json.loads(value)
            except ValueError:
                continue
        if isinstance(value, dict):
            return value
    return {}


def session_id_of(event):
    """The session id as a safe file stem: separators and leading dots removed, never empty."""
    raw = getattr(event, "raw", None) or {}
    given = getattr(event, "session_id", None) or (raw.get("session_id") if isinstance(raw, dict) else None)
    stem = "".join(c for c in str(given or "") if c.isalnum() or c in "._-").lstrip(".")
    return stem[:SESSION_ID_MAX] or SESSION_UNKNOWN_ID


def session_log_path(root, session_id):
    return Path(root).joinpath(*SESSION_STATE_PARTS, session_id + ".jsonl")


def session_for(event, root):
    """What a script gate receives as `session`: the id, the log's absolute path, this call's id."""
    session_id = session_id_of(event)
    return {
        "id": session_id,
        "log_path": session_log_path(root, session_id).as_posix(),
        "tool_use_id": getattr(event, "tool_use_id", None),
    }


def _mask_assignments(command):
    """`command` with the value of every `NAME=value` word masked: an env prefix is a secret's usual home."""
    words = []
    for word in command.split(" "):
        name, eq, _ = word.partition("=")
        words.append(name + eq + SESSION_MASK if eq and name.isidentifier() else word)
    return " ".join(words)


def _bare_url(url):
    """`url` without userinfo, query and fragment: where a token or a secret is usually carried."""
    url = url.split("#", 1)[0].split("?", 1)[0]
    scheme, sep, rest = url.partition("://")
    if not sep:
        return url
    authority, slash, tail = rest.partition("/")
    return scheme + sep + authority.rsplit("@", 1)[-1] + slash + tail


def _first_str(mapping, keys):
    for key in keys:
        value = mapping.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def session_summary(event):
    """The input of a tool call as {path?, command?, url?}: what a policy asks about, nothing else."""
    tool_input = tool_call_input(event)
    path = getattr(event, "path", None) or _first_str(tool_input, SESSION_PATH_KEYS)
    command = getattr(event, "command", None) or _first_str(tool_input, ("command",))
    url = _first_str(tool_input, SESSION_URL_KEYS)
    summary = {}
    if isinstance(path, str) and path:
        summary["path"] = path[:SESSION_FIELD_CAP]
    if isinstance(command, str) and command:
        summary["command"] = _mask_assignments(command.splitlines()[0] if command.strip() else "")[:SESSION_FIELD_CAP]
    if url:
        summary["url"] = _bare_url(url)[:SESSION_FIELD_CAP]
    return summary


def _response_failed(response):
    if not isinstance(response, dict):
        return False
    if response.get("is_error") is True or response.get("isError") is True or response.get("success") is False:
        return True
    code = response.get("exit_code", response.get("exitCode"))
    return bool(response.get("error")) or (isinstance(code, int) and code != 0)


def session_outcome(event):
    """`ok` or `error` for a finished call, from what the payload says; None before it ran."""
    if event.event == "tool_failure":
        return "error"
    if event.event != "post_tool":
        return None
    raw = getattr(event, "raw", None) or {}
    failed = any(_response_failed(raw.get(key)) for key in SESSION_RESPONSE_KEYS) if isinstance(raw, dict) else False
    return "error" if failed else "ok"


def _same_call(line, record):
    """Whether `line` is `record` already logged: same call id, or, with none, the same second and input."""
    try:
        seen = json.loads(line)
    except ValueError:
        return False
    if seen.get("phase") != record["phase"]:
        return False
    if record["tool_use_id"]:
        return seen.get("tool_use_id") == record["tool_use_id"]
    return not seen.get("tool_use_id") and all(
        seen.get(key) == record[key] for key in ("ts", "tool", "input", "outcome")
    )


def _prune_old(directory):
    cutoff = datetime.now(timezone.utc).timestamp() - SESSION_PRUNE_SECONDS
    for old in directory.glob("*.jsonl"):
        try:
            if old.stat().st_mtime < cutoff:
                old.unlink()
        except OSError:
            continue


def _append_bounded(path, line, record):
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines() if path.exists() else []
    if any(_same_call(seen, record) for seen in lines[-SESSION_DEDUPE_TAIL:]):
        return
    if len(lines) < SESSION_MAX_ENTRIES and path.exists() and path.stat().st_size < SESSION_TRIM_BYTES:
        with path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
        return
    kept = [*lines, line][-SESSION_MAX_ENTRIES:]
    scratch = path.with_suffix(".tmp")
    scratch.write_text("\n".join(kept) + "\n", encoding="utf-8")
    scratch.replace(path)


def session_record(root, event, phase, outcome=None):
    """Append one record for this call to its session's log. Best effort: never raises."""
    try:
        path = session_log_path(root, session_id_of(event))
        path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "session_id": path.stem,
            "phase": phase,
            "tool": str(getattr(event, "tool", None) or ""),
            "input": session_summary(event),
            "outcome": outcome,
            "tool_use_id": getattr(event, "tool_use_id", None),
        }
        _append_bounded(path, json.dumps(record, ensure_ascii=False, sort_keys=True), record)
        _prune_old(path.parent)
    except Exception:  # noqa: BLE001 -- a log must never change what the hook decides
        return
