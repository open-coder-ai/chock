"""The floor's built-in tamper rules: a guardrail the merge-base has and the head removed or weakened, by name.

Every rule compares the merge-base with the head (the base tip may have moved on since the pull
request forked; what it added there is not the pull request's to keep). The facts live in
`data/tamper.json`, inside the engine, so the pull request under judgement cannot edit them.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import cache
from typing import Any

from chock.display import inert
from chock.resources import package_data_dir
from chock.validation.floor_git import Revision

_SHOWN = 120
PACK_LIMIT = (
    "floor/pack-changed: the floor cannot tell a policy upgrade from a policy weakening offline; it lists every "
    "pack whose content or lock entry changed, and the base's gates still judge the pull request"
)


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


@dataclass(frozen=True)
class Revs:
    """The three commits a floor run reads: the base tip (whose config binds), the merge-base and the head."""

    base: Revision
    fork: Revision
    head: Revision


def shown(text: str) -> str:
    return text if len(text) <= _SHOWN else text[: _SHOWN - 3] + "..."


def as_json(text: str | None) -> Any:
    if text is None:
        return None
    try:
        return json.loads(text)
    except ValueError:
        return None


def changed(revs: Revs, prefix: str) -> list[str]:
    """Paths under `prefix` whose blob differs between the merge-base and the head (added, edited or deleted)."""
    paths = set(revs.fork.paths(prefix)) | set(revs.head.paths(prefix))
    return sorted(path for path in paths if revs.fork.oid(path) != revs.head.oid(path))


def _lock_entries(rev: Revision) -> dict[str, str]:
    doc = as_json(rev.text(facts()["lock_file"]))
    packs = doc.get("packs") if isinstance(doc, dict) else None
    return {str(p["id"]): json.dumps(p, sort_keys=True) for p in packs or () if isinstance(p, dict) and "id" in p}


def packs_changed(revs: Revs) -> frozenset[str]:
    """Pack ids whose `chock.lock` entry the pull request added or changed (merge-base -> head)."""
    was, now = _lock_entries(revs.fork), _lock_entries(revs.head)
    return frozenset(pack for pack, entry in now.items() if was.get(pack) != entry)


def lock_pack_removed(revs: Revs) -> list[Tamper]:
    lock = facts()["lock_file"]
    gone = sorted(set(_lock_entries(revs.fork)) - set(_lock_entries(revs.head)))
    return [
        Tamper("lock-pack-removed", lock, f"pack {pack!r} is locked at the merge-base, missing at the head")
        for pack in gone
    ]


def _pack_of(path: str) -> str:
    for prefix in (facts()["policies_prefix"], facts()["compiled_prefix"]):
        if path.startswith(prefix):
            return path.removeprefix(prefix).partition("/")[0]
    return ""


def pack_notes(revs: Revs, packs: frozenset[str]) -> list[str]:
    """One `floor/pack-changed` note per pack whose content or lock entry changed, naming every file of it the
    pull request changed; only a pack with a lock change has its source exempt from its own gates."""
    touched = {_pack_of(p) for prefix in ("policies_prefix", "compiled_prefix") for p in changed(revs, facts()[prefix])}
    notes: list[str] = []
    for pack in sorted((touched - {""}) | packs):
        source = changed(revs, f"{facts()['policies_prefix']}{pack}/")
        compiled = changed(revs, f"{facts()['compiled_prefix']}{pack}/")
        if pack in packs:
            detail = f"floor/pack-changed: {pack}: lock entry changed"
            if source:
                detail += f"; its own gates do not judge its source: {', '.join(map(inert, source))}"
        else:
            detail = f"floor/pack-changed: {pack}: no lock change, so every gate judged it"
            if source:
                detail += f"; source: {', '.join(map(inert, source))}"
        if compiled:
            detail += f"; compiled: {', '.join(map(inert, compiled))}"
        notes.append(detail)
    return [*notes, PACK_LIMIT] if notes else []


def tamper(revs: Revs, packs: frozenset[str]) -> list[Tamper]:
    """Every removal or weakening of a guardrail from merge-base to head, in rule order."""
    from chock.validation import tamper_files, tamper_hooks  # noqa: PLC0415 -- they import this module's facts

    return [
        *tamper_hooks.hook_removed(revs),
        *tamper_hooks.hooks_switched_off(revs),
        *tamper_files.gate_rules(revs, packs),
        *lock_pack_removed(revs),
        *tamper_files.runtime_rules(revs),
        *tamper_files.floor_workflow(revs),
    ]
