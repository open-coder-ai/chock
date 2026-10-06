"""A client's install steps from data: commands chock may run, notes to read, settings snippets to paste.

chock never edits a client's settings or config files: a `settings` step is printed, never written.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from chock.install import package


@dataclass(frozen=True)
class Step:
    """One rendered step: `command` (argv chock can run) or `text` (a note or a settings snippet to paste)."""

    command: list[str] | None = None
    text: str = ""


def _fill(value: Any, tokens: dict[str, str]) -> Any:
    """`value` with every `__TOKEN__` replaced, in keys and strings alike."""
    if isinstance(value, str):
        for token, filled in tokens.items():
            value = value.replace(token, filled)
        return value
    if isinstance(value, dict):
        return {_fill(k, tokens): _fill(v, tokens) for k, v in value.items()}
    return [_fill(v, tokens) for v in value] if isinstance(value, list) else value


def render(client_id: str, tokens: dict[str, str]) -> list[Step]:
    """The client's steps with the destination, plugin and marketplace filled in."""
    out = []
    for step in package.client(client_id)["steps"]:
        if "command" in step:
            out.append(Step(command=_fill(step["command"], tokens)))
        elif "settings" in step:
            out.append(Step(text=json.dumps(_fill(step["settings"], tokens), indent=2)))
        else:
            out.append(Step(text=_fill(step["note"], tokens)))
    return out
