"""What a published package enforces, read from the hooks it ships: the grade a bundle's claim is capped at."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
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
ADVISORY_SAYS = "advisory only. It is skill text, and nothing stops a violation"
_GUARD_SAYS = "refuses a matched shell command before it runs"
_GATE_ACTION_GRADE = {"warn": WARNS, "ask": ASKS}
_GATE_VERBS = {"block": "blocks", "ask": "asks", "warn": "warns"}


Reader = Callable[[str], str | None]
_INDEX_REF = re.compile(r"--multi \"?[^\" ]*?(scripts/chock_index/[^\" ]+\.json)")


def _members_of(command: str, read: Reader | None) -> list[str]:
    """What each member of a folded command's pinned index runs, as `--guard <script>` or `--gate <gate>` text."""
    ref = _INDEX_REF.search(command)
    text = read(ref.group(1)) if ref and read else None
    if text is None:
        return []
    try:
        return [" ".join(str(arg) for arg in member["argv"]) for member in json.loads(text)["members"]]
    except (ValueError, KeyError, TypeError):
        return []


def _hook_commands(node: Any, read: Reader | None = None) -> list[str]:
    """Every `command` string anywhere in a hooks document, nested or flat; a folded one with the members it runs.

    `read(path inside the package)` gives an index file's text, None where the package holds none.
    """
    if isinstance(node, dict):
        own = [node["command"]] if isinstance(node.get("command"), str) else []
        own += [m for c in own for m in _members_of(c, read)]
        return own + [c for value in node.values() for c in _hook_commands(value, read)]
    if isinstance(node, list):
        return [c for item in node for c in _hook_commands(item, read)]
    return []


def events_for(doc: Any, flag: str, read: Reader | None = None) -> list[str]:
    """The events whose entries run a command carrying `flag`, in the order the document wires them."""
    if isinstance(doc, list):  # a flat list of rules, each naming its `event` (kimi)
        rules = [r for r in doc if isinstance(r, dict) and any(flag in c for c in _hook_commands(r, read))]
        return list(dict.fromkeys(str(r.get("event")) for r in rules))
    events = doc.get("hooks", doc) if isinstance(doc, dict) else {}
    if not isinstance(events, dict):
        return []
    return [e for e, entries in events.items() if any(flag in c for c in _hook_commands(entries, read))]


def carries_guard(hooks_text: str | None, read: Reader | None = None) -> bool:
    """Whether a package's hooks document runs a shell guard."""
    return hooks_text is not None and any(_GUARD_FLAG in c for c in _hook_commands(json.loads(hooks_text), read))


def grade_of(
    hooks_text: str | None, gate_text: str | None, agent: str, *, write_judged: bool = True, read: Reader | None = None
) -> tuple[int, str]:
    """(grade, what it does) of one published package, from the hooks it ships and nothing else.

    `write_judged=False` is a client that runs the write hook but never names a write tool it matches.
    """
    if hooks_text is None:
        return ADVISORY, ADVISORY_SAYS
    doc = json.loads(hooks_text)
    group = vendors.hook_group(agent)
    if group and isinstance(doc, dict) and isinstance(doc.get(group), dict):
        doc = doc[group]
    commands = _hook_commands(doc, read)
    if any(_GATE_FLAG in c for c in commands):
        action = str((json.loads(gate_text) if gate_text else {}).get("action") or "block")
        writes = write_judged and vendors.pre_tool_event(agent) in events_for(doc, _GATE_FLAG, read)
        reach = (
            "on an agent's file writes and at turn end"
            if writes
            else "at turn end only. It does not check a file write when it happens"
        )
        grade = _GATE_ACTION_GRADE.get(action, BLOCKS if writes else STOP_ONLY)
        gate_says = f"{_GATE_VERBS.get(action, 'blocks')} {reach}"
        # A guard beside the gate blocks outright, so the gate's grade stays the package's floor.
        if any(_GUARD_FLAG in c for c in commands):
            return grade, f"{_GUARD_SAYS}. {gate_says[:1].upper()}{gate_says[1:]}"
        return grade, gate_says
    if any(_GUARD_FLAG in c for c in commands):
        return BLOCKS, _GUARD_SAYS
    return ADVISORY, ADVISORY_SAYS


def grade_of_files(files: dict[Path, str], hooks_rel: str, agent: str, *, write_judged: bool = True) -> tuple[int, str]:
    """`grade_of` for a package held in memory."""
    gate = files.get(Path(SCRIPTS_TEMPLATE.format(name=GATE_FILE)))
    return grade_of(
        files.get(Path(hooks_rel)), gate, agent, write_judged=write_judged, read=lambda rel: files.get(Path(rel))
    )


def enforcement_keyword(grade: int) -> str:
    """The manifest `enforcement` word a grade corresponds to."""
    return _ENFORCEMENT[grade]
