"""Tamper rules for agent hook registrations: an entry removed or retyped, or every hook switched off.

A hook entry's identity is (event, matcher, type, command). A matcher may widen, and the index pin a
regeneration rewrites (`--index-sha256 <sha256>`) is normalised; nothing else may change.
"""

from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass
from typing import Any

from chock.validation.tamper import Revs, Tamper, as_json, facts, shown

_UNIVERSAL = frozenset({"", "*"})


@dataclass(frozen=True)
class Hook:
    event: str
    matchers: frozenset[str]
    type: str
    command: tuple[tuple[str, str], ...]
    shown: str


def _norm(text: str) -> str:
    return re.sub(facts()["volatile_pattern"], facts()["volatile_placeholder"], text)


def pointed(doc: Any, pointer: str) -> Any:
    for part in [p for p in pointer.split("/") if p]:
        doc = doc.get(part) if isinstance(doc, dict) else None
    return doc


def _hook(event: str, matcher: object, item: dict) -> Hook | None:
    keys = facts()["hook_command_keys"]
    command = tuple((key, _norm(str(item[key]))) for key in keys if isinstance(item.get(key), str))
    if not command:
        return None
    raw = str(matcher) if isinstance(matcher, str) else ""
    matchers = frozenset(part.strip() for part in raw.split(facts()["hook_matcher_separator"]))
    kind = str(item.get(facts()["hook_type_key"], facts()["hook_type_default"]))
    return Hook(event, matchers, kind, command, shown(command[0][1]))


def hooks(doc: Any, pointer: str) -> list[Hook]:
    """Every (event, matcher, type, command) entry of a vendor hook file, nested or flat."""
    table = pointed(doc, pointer)
    found: list[Hook] = []
    nested, matcher_key = facts()["hook_nested_key"], facts()["hook_matcher_key"]
    for event, items in table.items() if isinstance(table, dict) else ():
        for item in items if isinstance(items, list) else ():
            if not isinstance(item, dict):
                continue
            inner = item.get(nested)
            leaves = [h for h in inner if isinstance(h, dict)] if isinstance(inner, list) else [item]
            for leaf in leaves:
                entry = _hook(str(event), leaf.get(matcher_key, item.get(matcher_key)), leaf)
                if entry is not None:
                    found.append(entry)
    return found


def _covers(head: frozenset[str], base: frozenset[str]) -> bool:
    return bool(head & _UNIVERSAL) or (not base & _UNIVERSAL and head >= base)


def _kept(entry: Hook, head: list[Hook]) -> bool:
    return any(
        (h.event, h.type, h.command) == (entry.event, entry.type, entry.command) and _covers(h.matchers, entry.matchers)
        for h in head
    )


def hook_files(rev_paths: list[str]) -> list[tuple[dict, str]]:
    """(spec, path) of every vendor hook file among `rev_paths`."""
    return [(spec, p) for spec in facts()["hook_files"] for p in rev_paths if fnmatch.fnmatchcase(p, spec["glob"])]


def hook_removed(revs: Revs) -> list[Tamper]:
    found: list[Tamper] = []
    for spec, path in hook_files(revs.fork.paths()):
        was = as_json(revs.fork.text(path))
        if was is None:
            continue
        now = as_json(revs.head.text(path))
        kept = hooks(now, spec["pointer"]) if now is not None else []
        for entry in hooks(was, spec["pointer"]):
            if not _kept(entry, kept):
                found.append(Tamper("hook-removed", path, f"{entry.event} {entry.type} hook removed: {entry.shown}"))
    return found


def _switched_on(doc: Any, keys: list[str]) -> list[str]:
    return [key for key in keys if pointed(doc, key) not in (None, False, 0, "", [], {})]


def hooks_switched_off(revs: Revs) -> list[Tamper]:
    """A disable key turned on in a vendor hook file, or a higher-precedence file added carrying hooks or one."""
    found: list[Tamper] = []
    switches = facts()["hook_switches"]
    for spec, path in hook_files(revs.head.paths()):
        keys = switches.get(spec["vendor"], {}).get("disable_keys", [])
        now = _switched_on(as_json(revs.head.text(path)), keys)
        was = set(_switched_on(as_json(revs.fork.text(path)), keys))
        found += [Tamper("hooks-disabled", path, f"{key} turns every hook off") for key in now if key not in was]
    for vendor, switch in sorted(switches.items()):
        keys = switch.get("disable_keys", [])
        for path in switch.get("override_files", []):
            if not revs.head.has(path) or revs.head.oid(path) == revs.fork.oid(path):
                continue
            doc = as_json(revs.head.text(path))
            carries = doc is None or pointed(doc, facts()["hook_nested_key"]) is not None or _switched_on(doc, keys)
            if carries:
                found.append(
                    Tamper(
                        "hooks-overridden",
                        path,
                        f"{vendor} reads this file over its hook file; it carries hooks or a disable key, or does not parse",
                    )
                )
    return found


def not_covered(revs: Revs) -> list[str]:
    """Vendors with a hook file at the merge-base whose switch-off keys this engine has not verified."""
    switches = facts()["hook_switches"]
    return sorted({spec["vendor"] for spec, _ in hook_files(revs.fork.paths())} - set(switches))
