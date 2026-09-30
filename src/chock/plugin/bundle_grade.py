"""What a published package enforces, read from the hooks it ships: the grade a bundle's claim is capped at."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from chock import vendors
from chock.compile.emitters.in_agent import GATE_FILE
from chock.plugin.store import SCRIPTS_TEMPLATE

#: The flag a hook command carries for each kind of enforcing package. A guard judges a shell
#: command before the client runs it; a gate judges what a turn writes. The page says which is
#: which by reading the published hooks, never by assuming every enforcing package is a guard.
_GUARD_FLAG = "--guard"
_GATE_FLAG = "--gate"


ADVISORY, WARNS, ASKS, STOP_ONLY, BLOCKS = range(5)
#: Keyword a bundle's weakest member lends it, in the manifest's own `enforcement` vocabulary.
_ENFORCEMENT = {ADVISORY: "advise", WARNS: "warn", ASKS: "ask", STOP_ONLY: "block", BLOCKS: "block"}
ADVISORY_SAYS = "advisory only: skill text, nothing stops a violation"
_GATE_ACTION_GRADE = {"warn": WARNS, "ask": ASKS}
_GATE_VERBS = {"block": "blocks", "ask": "asks", "warn": "warns"}


def _hook_commands(node: Any) -> list[str]:
    """Every `command` string anywhere in a hooks document, nested or flat."""
    if isinstance(node, dict):
        found = [node["command"]] if isinstance(node.get("command"), str) else []
        return found + [c for value in node.values() for c in _hook_commands(value)]
    if isinstance(node, list):
        return [c for item in node for c in _hook_commands(item)]
    return []


def _hook_events(doc: Any) -> list[str]:
    """The events a hooks document wires, in the order it wires them."""
    events = doc.get("hooks", doc) if isinstance(doc, dict) else {}
    return [event for event, entries in events.items() if isinstance(entries, list)] if isinstance(events, dict) else []


def grade_of(hooks_text: str | None, gate_text: str | None, agent: str) -> tuple[int, str]:
    """(grade, what it does) of one published package, from the hooks it ships and nothing else."""
    if hooks_text is None:
        return ADVISORY, ADVISORY_SAYS
    doc = json.loads(hooks_text)
    commands = _hook_commands(doc)
    if any(_GATE_FLAG in c for c in commands):
        action = str((json.loads(gate_text) if gate_text else {}).get("action") or "block")
        writes = vendors.pre_tool_event(agent) in _hook_events(doc)
        reach = (
            "on an agent's file writes and at turn end"
            if writes
            else "at turn end only; the write itself is not judged"
        )
        grade = _GATE_ACTION_GRADE.get(action, BLOCKS if writes else STOP_ONLY)
        return grade, f"{_GATE_VERBS.get(action, 'blocks')} {reach}"
    if any(_GUARD_FLAG in c for c in commands):
        return BLOCKS, "refuses a matched shell command before it runs"
    return ADVISORY, ADVISORY_SAYS


def grade_of_files(files: dict[Path, str], hooks_rel: str, agent: str) -> tuple[int, str]:
    """`grade_of` for a package held in memory."""
    gate = files.get(Path(SCRIPTS_TEMPLATE.format(name=GATE_FILE)))
    return grade_of(files.get(Path(hooks_rel)), gate, agent)


def enforcement_keyword(grade: int) -> str:
    """The manifest `enforcement` word a grade corresponds to."""
    return _ENFORCEMENT[grade]
