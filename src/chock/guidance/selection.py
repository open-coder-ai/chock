"""The repo's rule selection, read the way the catalog's gate reads it; never written."""

from __future__ import annotations

import json
from collections.abc import Mapping

from chock.guidance.source import GuidanceError

ALLOW, ASK, DENY = "allow", "ask", "deny"
VERDICTS = (ALLOW, ASK, DENY)
SCHEMA_VERSION = 2
_TOP_KEYS = frozenset({"version", "packs"})
_PACK_KEYS = frozenset({"verdict", "rules"})


def _verdict(where: str, value: object) -> str:
    if value not in VERDICTS:
        msg = f"{where} sets a verdict {value!r}; one of {list(VERDICTS)} is required"
        raise GuidanceError(msg)
    return str(value)


def _pack_verdicts(pack: str, ids: set[str], declared: object) -> dict[str, str]:
    where = f"selection pack {pack!r}"
    if declared is None:
        return dict.fromkeys(ids, DENY)
    if not isinstance(declared, dict) or set(declared) - _PACK_KEYS:
        msg = f"{where} must be an object with only {sorted(_PACK_KEYS)}"
        raise GuidanceError(msg)
    if "verdict" in declared:
        return dict.fromkeys(ids, _verdict(where, declared["verdict"]))
    spoken = declared.get("rules") or {}
    if not isinstance(spoken, dict) or set(spoken) - ids:
        msg = f"{where} 'rules' must map ids the pack contains to a verdict"
        raise GuidanceError(msg)
    return {i: _verdict(where, spoken[i]) if i in spoken else DENY for i in ids}


def parse(raw: str, packs: Mapping[str, set[str]]) -> dict[str, str]:
    """Every rule's verdict. A silent rule denies; an unreadable or unknown shape raises."""
    try:
        document = json.loads(raw)
    except json.JSONDecodeError as exc:
        msg = f"selection is not valid JSON ({exc.msg})"
        raise GuidanceError(msg) from exc
    if not isinstance(document, dict) or set(document) - _TOP_KEYS:
        msg = f"selection must be an object with only {sorted(_TOP_KEYS)}"
        raise GuidanceError(msg)
    if document.get("version") != SCHEMA_VERSION:
        msg = f"selection version {document.get('version')!r} is not read here; only version {SCHEMA_VERSION} is"
        raise GuidanceError(msg)
    declared = document.get("packs") or {}
    if not isinstance(declared, dict) or set(declared) - set(packs):
        msg = "selection 'packs' must be an object naming only packs the policy carries"
        raise GuidanceError(msg)
    verdicts: dict[str, str] = {}
    for pack, ids in packs.items():
        verdicts |= _pack_verdicts(pack, ids, declared.get(pack))
    return verdicts
