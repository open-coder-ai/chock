"""The floor's built-in tamper rules: a guardrail the base has and the head removed or weakened, by name.

Each rule compares base against head structurally and refuses only a removal or a weakening, so an
addition or a regeneration (`chock sync`) stays silent. The facts live in `data/tamper.json`, inside
the engine, so the pull request under judgement cannot edit them.
"""

from __future__ import annotations

import fnmatch
import json
import re
from dataclasses import dataclass
from functools import cache
from typing import Any

import yaml

from chock import yamlio
from chock.display import inert
from chock.gate.runner.constants import _ACTION_RANK
from chock.resources import package_data_dir
from chock.validation.floor_git import Revision

_UNIVERSAL = frozenset({"", "*"})
_SHOWN = 120
_CONFIG = ".chock/config.yaml"
#: YAML 1.1 reads a bare `on:` key as boolean true.
_ON_KEYS = ("on", True)


@cache
def facts() -> dict[str, Any]:
    return json.loads(package_data_dir("chock", "data").joinpath("tamper.json").read_text(encoding="utf-8"))


@dataclass(frozen=True)
class Tamper:
    rule: str
    path: str
    detail: str

    def render(self) -> str:
        return f"tamper/{self.rule} {inert(self.path)}: {inert(self.detail)}"


def _norm(text: str) -> str:
    """`text` with the parts a regeneration changes (hashes, versions) replaced by one placeholder."""
    return re.sub(facts()["volatile_pattern"], facts()["volatile_placeholder"], text)


def _shown(text: str) -> str:
    return text if len(text) <= _SHOWN else text[: _SHOWN - 3] + "..."


def _json(text: str | None) -> Any:
    if text is None:
        return None
    try:
        return json.loads(text)
    except ValueError:
        return None


# --- hook registrations ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Hook:
    event: str
    matchers: frozenset[str]
    command: tuple[tuple[str, str], ...]
    shown: str


def _pointed(doc: Any, pointer: str) -> Any:
    for part in [p for p in pointer.split("/") if p]:
        doc = doc.get(part) if isinstance(doc, dict) else None
    return doc


def _hook(event: str, matcher: object, item: dict) -> _Hook | None:
    keys = facts()["hook_command_keys"]
    command = tuple((key, _norm(str(item[key]))) for key in keys if isinstance(item.get(key), str))
    if not command:
        return None
    raw = str(matcher) if isinstance(matcher, str) else ""
    matchers = frozenset(part.strip() for part in raw.split(facts()["hook_matcher_separator"]))
    return _Hook(event, matchers, command, _shown(str(item[keys[0]] if keys[0] in item else command[0][1])))


def hooks(doc: Any, pointer: str) -> list[_Hook]:
    """Every (event, matcher, command) entry of a vendor hook file, nested or flat."""
    table = _pointed(doc, pointer)
    found: list[_Hook] = []
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


def _kept(entry: _Hook, head: list[_Hook]) -> bool:
    return any(
        h.event == entry.event and h.command == entry.command and _covers(h.matchers, entry.matchers) for h in head
    )


def hook_removed(base: Revision, head: Revision) -> list[Tamper]:
    found: list[Tamper] = []
    for spec in facts()["hook_files"]:
        for path in [p for p in base.paths() if fnmatch.fnmatchcase(p, spec["glob"])]:
            was = _json(base.text(path))
            if was is None:
                continue
            now = _json(head.text(path))
            kept = hooks(now, spec["pointer"]) if now is not None else []
            for entry in hooks(was, spec["pointer"]):
                if not _kept(entry, kept):
                    found.append(Tamper("hook-removed", path, f"{entry.event} hook removed: {entry.shown}"))
    return found


# --- compiled gates, the lock and the vendored runtime -------------------------------------------


def _gate_paths(rev: Revision) -> list[str]:
    prefix, name = facts()["compiled_prefix"], facts()["gate_file"]
    return [
        path
        for path in rev.paths(prefix)
        if any(fnmatch.fnmatchcase(path, f"{prefix}*/{surface}/{name}") for surface in facts()["gate_surfaces"])
    ]


def gate_rules(base: Revision, head: Revision) -> list[Tamper]:
    found: list[Tamper] = []
    for path in _gate_paths(base):
        was = _json(base.text(path))
        if not isinstance(was, dict):
            continue
        if not head.has(path):
            found.append(Tamper("gate-removed", path, "compiled gate present at the base, deleted at the head"))
            continue
        now = _json(head.text(path))
        if not isinstance(now, dict):
            found.append(Tamper("gate-weakened", path, "gate is not a JSON object at the head"))
            continue
        lost = sorted(set(was.get("on") or []) - set(now.get("on") or []))
        if lost:
            found.append(Tamper("gate-weakened", path, f"no longer bound to: {', '.join(map(str, lost))}"))
        was_action, now_action = str(was.get("action", "block")), str(now.get("action", "block"))
        if _ACTION_RANK.get(now_action, -1) < _ACTION_RANK.get(was_action, -1):
            found.append(Tamper("gate-weakened", path, f"action {was_action} -> {now_action}"))
    return found


def _pack_ids(text: str | None) -> set[str]:
    doc = _json(text)
    packs = doc.get("packs") if isinstance(doc, dict) else None
    return {str(p["id"]) for p in packs or () if isinstance(p, dict) and "id" in p}


def lock_pack_removed(base: Revision, head: Revision) -> list[Tamper]:
    lock = facts()["lock_file"]
    gone = sorted(_pack_ids(base.text(lock)) - _pack_ids(head.text(lock)))
    return [
        Tamper("lock-pack-removed", lock, f"pack {pack!r} is locked at the base, missing at the head") for pack in gone
    ]


def runtime_removed(base: Revision, head: Revision) -> list[Tamper]:
    prefix = facts()["runtime_prefix"]
    kept = {_norm(path) for path in head.paths(prefix)}
    return [
        Tamper("runtime-removed", path, "vendored runtime file deleted")
        for path in base.paths(prefix)
        if _norm(path) not in kept
    ]


# --- the required workflow ------------------------------------------------------------------------


def _yaml(text: str | None) -> Any:
    if text is None:
        return None
    try:
        return yamlio.safe_load(text)
    except yaml.YAMLError:
        return None


def workflow_path(base: Revision) -> str:
    """The workflow the floor guards: the base config's `floor_workflow`, else the default."""
    config = _yaml(base.text(_CONFIG))
    named = config.get(facts()["workflow_config_key"]) if isinstance(config, dict) else None
    return named if isinstance(named, str) and named.strip() else facts()["workflow_default"]


def _triggers(doc: dict) -> set[str]:
    raw = next((doc[key] for key in _ON_KEYS if key in doc), None)
    if isinstance(raw, str):
        return {raw}
    return {str(t) for t in raw} if isinstance(raw, list | dict) else set()


def _steps(job: object) -> set[tuple[str, str]]:
    steps = job.get("steps") if isinstance(job, dict) else None
    return {
        (str(s.get("name", "")), _norm(str(s.get("run") or s.get("uses") or "")))
        for s in steps or ()
        if isinstance(s, dict)
    }


def ci_step_removed(base: Revision, head: Revision) -> list[Tamper]:
    path = workflow_path(base)
    was = _yaml(base.text(path))
    if not isinstance(was, dict):
        return []
    now = _yaml(head.text(path))
    if not isinstance(now, dict):
        return [Tamper("ci-step-removed", path, "workflow deleted or unreadable at the head")]
    found = [Tamper("ci-step-removed", path, f"trigger {t!r} removed") for t in sorted(_triggers(was) - _triggers(now))]
    head_jobs = now.get("jobs") if isinstance(now.get("jobs"), dict) else {}
    base_jobs = was.get("jobs") if isinstance(was.get("jobs"), dict) else {}
    for job_id, job in base_jobs.items():
        if job_id not in head_jobs:
            found.append(Tamper("ci-step-removed", path, f"job {job_id!r} removed"))
            continue
        for name, body in sorted(_steps(job) - _steps(head_jobs[job_id])):
            found.append(Tamper("ci-step-removed", path, f"job {job_id!r}: step {_shown(name or body)!r} removed"))
    return found


RULES = (hook_removed, gate_rules, lock_pack_removed, runtime_removed, ci_step_removed)


def tamper(base: Revision, head: Revision) -> list[Tamper]:
    """Every removal or weakening of a guardrail from base to head, in rule order."""
    return [finding for rule in RULES for finding in rule(base, head)]
