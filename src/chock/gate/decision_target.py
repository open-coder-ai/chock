"""Who did what, for a decision line: session_id, actor and a tool call's `target`. Stdlib only, never raises.

`target` is a fingerprint, never content: a repo-relative path, `outside:sha256:<hex>`, `<program> sha256:<hex>`
of a whole command (no argument), or `<server>/<tool>`. Spec: docs/decision-log.md.
"""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path

from .runner.journal import LOG_CALL, log_redact

DLOG_AGENT_PREFIX = "agent:"
_DLOG_HASH_PREFIX, _DLOG_OUTSIDE_PREFIX = "sha256:", "outside:"
#: Claude Code's MCP tool name, `mcp__<server>__<tool>`; Windsurf's adapter already gives `<server>/<tool>`.
_DLOG_MCP_TOOL = re.compile(r"^mcp__(?P<server>.+?)__(?P<tool>.+)$")
#: `NAME=value` words before a command's program: an env prefix, never the program.
_DLOG_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_DLOG_OPAQUE_MARKS = ("$(", "`", "'", '"')
#: A program name written as is: letters and `._+-`, no digit, no path, no quote or redirect. Else `-`.
_DLOG_PLAIN_PROGRAM = re.compile(r"^[A-Za-z][A-Za-z._+-]{0,63}$")
#: Command names written even with a digit or a path before them (`/usr/bin/git`): the name says nothing private.
_DLOG_KNOWN_PROGRAMS = frozenset(
    [
        "awk",
        "bash",
        "base64",
        "cat",
        "cd",
        "chmod",
        "cp",
        "curl",
        "diff",
        "docker",
        "echo",
        "env",
        "find",
        "gh",
        "git",
        "go",
        "gpg2",
        "grep",
        "head",
        "jq",
        "ls",
        "make",
        "md5sum",
        "mkdir",
        "mv",
        "node",
        "npm",
        "npx",
        "pip",
        "pip3",
        "pnpm",
        "pwsh",
        "pytest",
        "python",
        "python2",
        "python3",
        "rg",
        "rm",
        "ruff",
        "sed",
        "sh",
        "sha1sum",
        "sha256sum",
        "sort",
        "tail",
        "tar",
        "test",
        "uv",
        "wc",
        "wget",
        "xargs",
        "yarn",
        "zsh",
    ]
)
_DLOG_PROGRAM_CAP = 64
#: An MCP `server/tool` is cut to this many characters, after redaction.
_DLOG_MCP_CAP = 128
#: `client_type` as an actor names it: lower case, these characters only, at most 32.
_DLOG_CLIENT_UNSAFE = re.compile(r"[^a-z0-9_-]")
_DLOG_CLIENT_CAP = 32
#: A Windows drive (`C:\`, `C:x`) or UNC (`\\server\`) path: absolute on Windows, never inside a POSIX repo.
_DLOG_WINDOWS_PATH = re.compile(r"^(?:[A-Za-z]:|\\\\)")
_DLOG_UNNAMED = "-"


def dlog_session(event, record):
    """`record` with the client's session id, where the payload carries one: what groups a session's lines."""
    session = getattr(event, "session_id", None)
    if isinstance(session, str) and session:
        record["session_id"] = session
    return record


def _dlog_client(raw):
    """The payload's `client_type` as `[a-z0-9_-]{1,32}`, or None when nothing of it is left."""
    named = raw.get("client_type") if isinstance(raw, dict) else None
    if not isinstance(named, str):
        return None
    return _DLOG_CLIENT_UNSAFE.sub("", named.lower())[:_DLOG_CLIENT_CAP] or None


def dlog_actor(event):
    """`agent:<client>`: an agent hook is always an agent's call; the client named in the payload, else the bundle's."""
    named = _dlog_client(getattr(event, "raw", None)) or getattr(event, "agent", None)
    return DLOG_AGENT_PREFIX + str(named or "unknown")


def _dlog_sha256(text):
    return _DLOG_HASH_PREFIX + hashlib.sha256(str(text).encode("utf-8", "surrogatepass")).hexdigest()


def _dlog_program(command):
    """The program's bare name: after plain `NAME=value` words; `-` when a shell parser would be needed to tell."""
    for word in str(command).split():
        if not _DLOG_ASSIGNMENT.match(word):
            return "" if word.startswith("-") else word
        if any(mark in word for mark in _DLOG_OPAQUE_MARKS):  # `X=$(...)`, a quote: where it ends is unknowable here
            return ""
    return ""


def dlog_command_print(command):
    """`<program> sha256:<hex of the whole command>`: the program's bare name only, never an argument."""
    program = _dlog_program(command)
    base = re.split(r"[\\/]", program)[-1]
    known = base in _DLOG_KNOWN_PROGRAMS or _DLOG_PLAIN_PROGRAM.match(program)
    return f"{log_redact(base) if known else _DLOG_UNNAMED} {_dlog_sha256(command)}"


def dlog_path_print(path, cwd, repo):
    """The repository-relative path; any path outside `repo` (or with no repo) is `outside:sha256:<hex>`."""
    if os.sep == "/" and _DLOG_WINDOWS_PATH.match(str(path)):
        return _DLOG_OUTSIDE_PREFIX + _dlog_sha256(path)
    full = os.path.realpath(os.path.join(cwd or os.getcwd(), str(path)))
    if repo is not None:
        try:
            return log_redact(Path(full).relative_to(os.path.realpath(repo)).as_posix())
        except ValueError:
            pass
    return _DLOG_OUTSIDE_PREFIX + _dlog_sha256(full)


def dlog_target(event, repo):
    """What a tool call touched, as a fingerprint: `server/tool`, a command's print, a path's; None off a tool call."""
    if getattr(event, "event", None) != "pre_tool":
        return None
    tool = str(getattr(event, "tool", None) or "")
    mcp = _DLOG_MCP_TOOL.match(tool)
    if mcp:
        server, name = mcp["server"], mcp["tool"]
        return log_redact(f"{server}/{name}")[:_DLOG_MCP_CAP]
    command, path = getattr(event, "command", None), getattr(event, "path", None)
    if command:
        return dlog_command_print(command)
    if path:
        return dlog_path_print(path, getattr(event, "cwd", None), repo)
    return log_redact(tool)[:_DLOG_PROGRAM_CAP] or None


def dlog_fields(event, repo):
    """Who did what, for a decision line: session_id, actor, and target on a tool call. Never raises: {} instead."""
    try:
        fields = dlog_session(event, {"actor": dlog_actor(event)})
        target = dlog_target(event, repo)
    except Exception:  # noqa: BLE001 -- a log field must never change the decision, and gate calls this inline
        return {}
    if target:
        fields["target"] = target
    call = getattr(event, "tool_use_id", None)
    if target and isinstance(call, str) and call:
        fields[LOG_CALL] = call
    return fields
