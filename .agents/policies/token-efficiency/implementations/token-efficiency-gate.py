"""Warn on a third identical Read of a file, or a command retried past the retry cap."""

from __future__ import annotations

import importlib
import json
import os
import sys

READ_REPEAT = 3
RETRY_CAP = 3
EDITS = ("Edit", "Write", "MultiEdit", "NotebookEdit")
PATH_KEYS = ("file_path", "filePath", "path", "notebook_path", "target_file", "TargetFile")
FIELD_CAP = 300


def load_log(root: str):
    """The vendored session reader, or None when this install has none."""
    sys.path.insert(0, os.path.join(root, ".chock", "bin"))
    try:
        return importlib.import_module("chock_session")
    except ImportError:
        return None


def logged_command(command: str) -> str:
    """The command as the session log stores it: first line, NAME=value words masked, capped."""
    words = []
    for word in command.splitlines()[0].split(" "):
        name, eq, _ = word.partition("=")
        words.append(name + eq + "***" if eq and name.isidentifier() else word)
    return " ".join(words)[:FIELD_CAP]


def reads_since_edit(log, records, path: str) -> int:
    """Reads of `path` logged since it was last edited."""
    reads = 0
    for record in records:
        if (record.get("input") or {}).get("path") != path:
            continue
        if record.get("tool") in EDITS:
            reads = 0
        elif record.get("tool") == "Read" and record.get("phase") == log.PRE and record.get("outcome") != "blocked":
            reads += 1
    return reads


def failures_since_success(log, records, command: str) -> int:
    """Failed runs of `command` since it last succeeded."""
    failures = 0
    for record in log.matching(records, tool="Bash", phase=log.POST, command=command):
        failures = failures + 1 if record.get("outcome") == log.ERROR else 0
    return failures


def judge(log, payload: dict) -> str:
    """The warning for this call, or an empty string."""
    records = log.prior(payload.get("session") or {})
    tool_input = payload.get("input") or {}
    if payload.get("tool") == "Read":
        path = next((tool_input[k] for k in PATH_KEYS if isinstance(tool_input.get(k), str) and tool_input[k]), "")
        if path and reads_since_edit(log, records, path) >= READ_REPEAT - 1:
            return (
                f"{path} was already read {READ_REPEAT - 1} times since it last changed; reuse what you have, "
                "read only the range you need, or ignore this if you are paging through a large file."
            )
    command = tool_input.get("command")
    if payload.get("tool") == "Bash" and isinstance(command, str) and len(command.strip().splitlines()) == 1:
        failed = failures_since_success(log, records, logged_command(command))
        if failed >= RETRY_CAP:
            return f"this exact command has failed {failed} times (retry cap {RETRY_CAP}); read the error and change approach."
    return ""


def main() -> int:
    payload = json.load(sys.stdin)
    log = load_log(str(payload.get("repo_root", ".")))
    message = judge(log, payload) if log else ""
    if message:
        sys.stderr.write(message)
        return 4
    return 0


if __name__ == "__main__":
    sys.exit(main())
