"""Read a chock session log from a policy script. Stdlib only; copy this file or import it.

`chock sync` vendors it as `chock_session.py` beside the runtimes in the chock bin directory. A
script gate receives `payload["session"] == {"id", "log_path", "tool_use_id"}`; the record format
is in `spec/session-log.md`. Every function tolerates a missing or damaged log and returns nothing.
"""

from __future__ import annotations

import json
from pathlib import Path

PRE, POST = "pre", "post"
ERROR = "error"
FIELDS = ("path", "command", "url")


def entries(session_or_path):
    """Every readable record, oldest first, from a `session` dict or a log path."""
    given = session_or_path.get("log_path") if isinstance(session_or_path, dict) else session_or_path
    try:
        lines = Path(str(given)).read_text(encoding="utf-8", errors="replace").splitlines()
    except (OSError, TypeError):
        return []
    found = []
    for line in lines:
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if isinstance(record, dict):
            found.append(record)
    return found


def prior(session):
    """Records of earlier calls: the current call's own `pre` record, if already logged, is left out."""
    current = session.get("tool_use_id") if isinstance(session, dict) else None
    return [r for r in entries(session) if not (current and r.get("tool_use_id") == current)]


def matching(records, tool=None, phase=None, outcome=None, **input_fields):
    """Records with this tool, phase, outcome and input fields (`path=`, `command=`, `url=`)."""
    unknown = set(input_fields) - set(FIELDS)
    if unknown:
        raise TypeError("unknown input field(s): " + ", ".join(sorted(unknown)))
    return [
        r
        for r in records
        if (tool is None or r.get("tool") == tool)
        and (phase is None or r.get("phase") == phase)
        and (outcome is None or r.get("outcome") == outcome)
        and all((r.get("input") or {}).get(k) == v for k, v in input_fields.items())
    ]


def count(records, **criteria):
    """How many `matching` records: `count(prior(s), tool="Bash", phase=PRE, command="make test")` is a retry count."""
    return len(matching(records, **criteria))


def failed(records, **criteria):
    """Whether a matching call finished in error: `failed(prior(s), tool="WebFetch", url=u)`."""
    return bool(matching(records, phase=POST, outcome=ERROR, **criteria))
