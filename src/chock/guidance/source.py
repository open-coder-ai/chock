"""Bounded, read-only access to the installed policies and selection files inside one repo."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from chock.guidance.match import RuleInfo, words

POLICIES_DIR = ".agents/policies"
CONTRACT = "skills/{id}/references/setup-contract.json"
_FIX_SEPARATOR = " -- "
_ELLIPSIS = " …"
_MIN_HEAD = 40


class GuidanceError(Exception):
    """Something this server cannot read or decide; the caller reports it, never guesses."""


def read_text(repo: Path, rel: str, cap: int) -> str | None:
    """A file under `repo` as text; None when absent. Symlinks, non-files and oversize raise."""
    path = repo
    for part in Path(rel).parts:
        path = path / part
        if path.is_symlink():
            msg = f"{rel} passes through a symlink; refusing to follow it"
            raise GuidanceError(msg)
    if not path.exists():
        return None
    if not path.is_file():
        msg = f"{rel} is not a regular file"
        raise GuidanceError(msg)
    if path.stat().st_size > cap:
        msg = f"{rel} is larger than {cap} bytes; refusing to read it"
        raise GuidanceError(msg)
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        msg = f"{rel} cannot be read as UTF-8 text"
        raise GuidanceError(msg) from exc


def abridge(constraint: str, cap: int) -> str:
    """The rule's own constraint text, cut to `cap` characters; the text after ` -- ` (its fix) survives the cut."""
    if len(constraint) <= cap:
        return constraint
    head, separator, tail = constraint.partition(_FIX_SEPARATOR)
    tail = tail[: cap // 2] if separator else ""
    room = max(cap - len(tail) - len(_ELLIPSIS) - len(separator), _MIN_HEAD)
    return head[:room].rsplit(" ", 1)[0].rstrip(",;:") + _ELLIPSIS + (separator + tail if separator else "")


@dataclass(frozen=True)
class Catalog:
    """One installed policy's rules, read from its shipped setup contract."""

    policy: str
    rules: list[RuleInfo]

    def packs(self) -> dict[str, set[str]]:
        found: dict[str, set[str]] = {}
        for rule in self.rules:
            found.setdefault(rule.pack, set()).add(rule.id)
        return found


def _rule(entry: object, stopwords: frozenset[str], constraint_chars: int) -> RuleInfo:
    if not isinstance(entry, dict) or not all(isinstance(entry.get(k), str) for k in ("id", "pack", "constraint")):
        msg = "a rule entry lacks a string id, pack or constraint"
        raise GuidanceError(msg)
    cwe = entry.get("cwe") or []
    if not isinstance(cwe, list):
        msg = f"rule {entry['id']} has a cwe that is not a list"
        raise GuidanceError(msg)
    cwe_items = [c for c in cwe if isinstance(c, dict) and isinstance(c.get("id"), str)]
    name_text = " ".join(
        [entry["id"].replace("-", " "), str(entry.get("title", ""))] + [str(c.get("name", "")) for c in cwe_items]
    )
    body_text = f"{entry.get('refuses', '')} {entry['constraint']}"
    return RuleInfo(
        id=entry["id"],
        pack=entry["pack"],
        title=str(entry.get("title", "")),
        constraint=abridge(entry["constraint"], constraint_chars),
        cwe=tuple(c["id"] for c in cwe_items),
        names=frozenset(words(name_text, stopwords)),
        body=frozenset(words(body_text, stopwords)),
    )


def load_catalog(repo: Path, policy: str, limits: dict, stopwords: frozenset[str]) -> Catalog | None:
    """The policy's rules, or None when it is not installed. A contract it cannot read raises."""
    if read_text(repo, f"{POLICIES_DIR}/{policy}/manifest.yaml", limits["file_bytes"]) is None:
        return None
    rel = f"{POLICIES_DIR}/{policy}/" + CONTRACT.format(id=policy)
    raw = read_text(repo, rel, limits["file_bytes"])
    if raw is None:
        msg = f"{policy} is installed but {rel} is missing"
        raise GuidanceError(msg)
    try:
        entries = json.loads(raw).get("rules")
    except (json.JSONDecodeError, AttributeError, RecursionError) as exc:
        msg = f"{rel} is not a setup contract"
        raise GuidanceError(msg) from exc
    if not isinstance(entries, list):
        msg = f"{rel} has no rules list"
        raise GuidanceError(msg)
    return Catalog(policy, [_rule(e, stopwords, limits["constraint_chars"]) for e in entries])
