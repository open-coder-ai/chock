"""A rule's verdict loosened against the base, reading the selection files the way their runtimes do.

`.chock/security.json` (java-security) and `.chock/agentic-security.json` (agentic-code-security) set
each rule's verdict. Their readers live in those policies; this mirrors their semantics so the check and
the runtime agree. The engine does not know the rule lists, so a pack's unnamed rules stand as one key.

Where the check cannot see what the runtime would enforce, it fails closed instead of matching:
- a head selection that is a symlink, a directory or another non-regular file is an error: the runtime
  reads through a link to text outside the diff, and past a dangling one or a directory as if absent;
- java-security falls back to the user-level `~/.chock/security.json` when the repository has none, so
  deleting a committed java selection is a loosening, whatever the base said.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

ALLOW, ASK, DENY = "allow", "ask", "deny"
_RANK = {DENY: 0, ASK: 1, ALLOW: 2}
_TOP_KEYS = frozenset({"version", "packs"})
_PACK_KEYS = frozenset({"verdict", "rules"})
_LEGACY_PACK = "java"


class SelectionInvalidError(ValueError):
    """Text the runtime would refuse: no verdict can be read from it."""


@dataclass(frozen=True)
class Kind:
    """One selection file and what its reader does with silence and with a pack verdict."""

    filename: str
    versions: frozenset[int]
    verdicts: frozenset[str]
    default: str | None  # what a rule nobody spoke for does; None when each rule carries its own default
    verdict_ends_rules: bool = field(kw_only=True)  # java ignores `rules` beside a verdict; agentic lets them override
    lenient: bool = field(kw_only=True)  # a falsy `packs` or `rules`, or a null pack, reads as omitted
    fallback: str | None = field(default=None, kw_only=True)  # what deleting the file hands verdicts to


JAVA = Kind(
    ".chock/security.json",
    frozenset({1, 2}),
    frozenset({ALLOW, ASK, DENY}),
    DENY,
    verdict_ends_rules=True,
    lenient=True,
    fallback="deleting the repo selection hands verdicts to ~/.chock/security.json",
)
AGENTIC = Kind(
    ".chock/agentic-security.json",
    frozenset({1}),
    frozenset({ALLOW, DENY}),
    None,
    verdict_ends_rules=False,
    lenient=False,
)
KINDS = (JAVA, AGENTIC)


@dataclass(frozen=True)
class Selection:
    """A parsed file: each pack's (verdict, rules). `legacy` is java-security's version 1 shape."""

    packs: dict[str, tuple[str | None, dict[str, str]]]
    legacy: bool = False


def _verdict(kind: Kind, value: object) -> str:
    if not isinstance(value, str) or value not in kind.verdicts:
        msg = f"{kind.filename}: a verdict is one of {sorted(kind.verdicts)}, got {value!r}"
        raise SelectionInvalidError(msg)
    return value


def _object(kind: Kind, value: object, where: str, *, keys: frozenset[str] | None = None) -> dict:
    if not value and kind.lenient and keys is None:
        return {}
    if not isinstance(value, dict):
        msg = f"{kind.filename}: {where} must be an object"
        raise SelectionInvalidError(msg)
    if keys is not None and (extra := sorted(set(value) - keys)):
        msg = f"{kind.filename}: {where} has unknown key(s) {extra}"
        raise SelectionInvalidError(msg)
    return value


def _pack(kind: Kind, name: str, body: object) -> tuple[str | None, dict[str, str]]:
    where = f"pack {name!r}"
    if body is None and kind.lenient:
        return None, {}
    declared = _object(kind, body, where, keys=_PACK_KEYS)
    verdict = _verdict(kind, declared["verdict"]) if "verdict" in declared else None
    if verdict and kind.verdict_ends_rules:
        return verdict, {}
    spoken = _object(kind, declared.get("rules", {}), f"{where} rules")
    return verdict, {rule: _verdict(kind, value) for rule, value in spoken.items()}


def parse(kind: Kind, text: str | None) -> Selection:
    """The selection `text` states; None is an absent file. Raises SelectionInvalidError where the runtime refuses."""
    if text is None:
        return Selection({})
    try:
        document: Any = json.loads(text)
    except json.JSONDecodeError as exc:
        msg = f"{kind.filename} is not valid JSON: {exc}"
        raise SelectionInvalidError(msg) from exc
    document = _object(kind, document, "the selection", keys=_TOP_KEYS)
    version = document.get("version")
    if not any(version == known for known in kind.versions):  # as the runtime: True and 2.0 equal 1 and 2
        msg = f"{kind.filename}: version must be one of {sorted(kind.versions)}, got {version!r}"
        raise SelectionInvalidError(msg)
    declared = _object(kind, document.get("packs", {}), "packs")
    legacy = kind is JAVA and version == 1
    if legacy and (other := sorted(set(declared) - {_LEGACY_PACK})):
        msg = f"{kind.filename}: a version-1 selection has only {_LEGACY_PACK!r}, got {other}"
        raise SelectionInvalidError(msg)
    return Selection({name: _pack(kind, name, body) for name, body in declared.items()}, legacy)


def _candidates(kind: Kind, sel: Selection, pack: str | None, rule: str | None) -> list[str | None]:
    """The verdicts `rule` (None: every rule the file does not name) may get; several when the pack is unknown."""
    if sel.legacy:
        verdict, rules = sel.packs.get(_LEGACY_PACK, (None, {}))
        if verdict is None and rule in rules:
            return [rules[rule]]
        return [verdict, kind.default] if verdict else [kind.default]
    names = [pack] if pack is not None else sorted(sel.packs)
    found: list[str | None] = [kind.default] if not names else []
    for name in names:
        verdict, rules = sel.packs.get(name, (None, {}))
        if rule in rules and not (verdict and kind.verdict_ends_rules):
            found.append(rules[rule])
        else:
            found.append(verdict or kind.default)
    return found


def _effective(kind: Kind, sel: Selection, key: tuple[str | None, str | None], *, upper: bool) -> str | None:
    """One verdict from the candidates: the looser (`upper`) or tighter reading where a v1 file is ambiguous."""
    found = _candidates(kind, sel, *key)
    known = [v for v in found if v is not None]
    if not known or len(known) < len(found):
        return None
    return (max if upper else min)(known, key=_RANK.__getitem__)


def _keys(base: Selection, head: Selection) -> set[tuple[str | None, str | None]]:
    keys: set[tuple[str | None, str | None]] = set()
    for sel in (base, head):
        if sel.legacy:
            keys |= {(None, None), *((None, rule) for rule in sel.packs.get(_LEGACY_PACK, (None, {}))[1])}
            continue
        for pack, (_, rules) in sel.packs.items():
            keys |= {(pack, None), *((pack, rule) for rule in rules)}
    return keys


def _looser(was: str | None, now: str | None) -> bool:
    if was is None or now is None:
        return (was == DENY and now is None) or (was is None and now == ALLOW)
    return _RANK[now] > _RANK[was]


@dataclass(frozen=True)
class Loosened:
    """One rule, or one pack's unnamed rules, that the head lets off more than the base does."""

    filename: str
    pack: str | None
    rule: str | None
    was: str | None
    now: str | None
    why: str | None = None  # the whole file's loosening, in place of one rule's

    def render(self) -> str:
        if self.why:
            return f"{self.filename}: {self.why}"
        where = f"pack {self.pack!r}" if self.pack else "a rule"
        what = f"rule {self.rule!r}" if self.rule else "every rule it does not name"
        was, now = self.was or "its default", self.now or "its default"
        return f"{self.filename}: {where}, {what}: {was} -> {now}"


def loosened(kind: Kind, base_text: str | None, head_text: str | None) -> list[Loosened]:
    """Every rule whose verdict the head loosens against the base. Raises SelectionInvalidError on unreadable text."""
    if base_text == head_text:
        return []
    if kind.fallback and base_text is not None and head_text is None:
        return [Loosened(kind.filename, None, None, None, None, kind.fallback)]
    base, head = parse(kind, base_text), parse(kind, head_text)
    mixed = base.legacy != head.legacy
    found = []
    for key in sorted(_keys(base, head), key=lambda k: (k[0] or "", k[1] or "")):
        was = _effective(kind, base, key, upper=not mixed)
        now = _effective(kind, head, key, upper=True)
        if _looser(was, now):
            found.append(Loosened(kind.filename, *key, was, now))
    return found
