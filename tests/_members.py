"""Read an installed hook config through the pinned policy index: one entry per member, as each policy had before the fold."""

from __future__ import annotations

import copy
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from chock.hooks.multi_wiring import INDEX_SHA_FLAG, MULTI_FLAG

FOLDED = re.compile(
    rf"{re.escape(MULTI_FLAG)} (?P<q>\\?\"?)(?P<rel>[^\s\"\\]+)\\?\"? {re.escape(INDEX_SHA_FLAG)} (?P<pin>[0-9a-f]{{64}})"
)


def index_members(root: Path, rel: str, pin: str) -> list[dict[str, Any]]:
    """The members of the index at `rel`, which must hash to `pin`: the same check the runtime makes."""
    body = (Path(root) / rel).read_bytes()
    assert hashlib.sha256(body).hexdigest() == pin, f"{rel} does not match the pin in its command"
    return json.loads(body)["members"]


def member_text(member: dict[str, Any], quote: str) -> str:
    """The tail of the per-policy command this member stands for: its flag, its file (quoted as the command was), the rest."""
    flag, target, *rest = member["argv"]
    return " ".join([flag, f"{quote}{target}{quote}", *rest])


def _folded(node: Any) -> bool:
    if isinstance(node, str):
        return FOLDED.search(node) is not None
    if isinstance(node, dict):
        return any(_folded(v) for v in node.values())
    return any(_folded(v) for v in node) if isinstance(node, list) else False


def _one(root: Path, node: Any, which: int) -> Any:
    """`node` with every folded segment replaced by member number `which` of its index."""
    if isinstance(node, str):
        return FOLDED.sub(lambda m: member_text(index_members(root, m["rel"], m["pin"])[which], m["q"]), node)
    if isinstance(node, dict):
        return {k: _one(root, v, which) for k, v in node.items()}
    return [_one(root, v, which) for v in node] if isinstance(node, list) else node


def _count(root: Path, node: Any) -> int:
    for text in _strings(node):
        if (found := FOLDED.search(text)) is not None:
            return len(index_members(root, found["rel"], found["pin"]))
    return 0


def _strings(node: Any) -> list[str]:
    if isinstance(node, str):
        return [node]
    if isinstance(node, dict):
        return [s for v in node.values() for s in _strings(v)]
    return [s for v in node for s in _strings(v)] if isinstance(node, list) else []


def unfold(root: Path | str, node: Any) -> Any:
    """`node` (a parsed config) with each folded entry replaced by one entry per member of its verified index.

    Every unfolded entry carries the entry's own timeout and matcher and the command text that member's
    policy had when it was installed by itself, so an assertion about one policy's command reads it from that
    policy's member: the same flag, the same path, the same timeout.
    """
    root = Path(root)
    if isinstance(node, list):
        out: list[Any] = []
        for item in node:
            if isinstance(item, dict) and _folded(item):
                out += [_one(root, copy.deepcopy(item), i) for i in range(_count(root, item))]
            else:
                out.append(unfold(root, item))
        return out
    if isinstance(node, dict):
        return {k: unfold(root, v) for k, v in node.items()}
    return node


def unfold_text(root: Path | str, text: str) -> str:
    """The same for a config read as text: its JSON unfolded and written back."""
    return json.dumps(unfold(root, json.loads(text)))


def drop_members(root: Path | str, node: Any, drop: Any) -> Any:
    """`node` with every member whose command text `drop` accepts removed from its index, which is rewritten and re-pinned.

    An entry left with no member is dropped, as a policy with no entry of that kind never had one.
    """
    root = Path(root)
    if isinstance(node, list):
        out: list[Any] = []
        for item in node:
            if isinstance(item, dict) and _folded(item):
                found = next(m for s in _strings(item) if (m := FOLDED.search(s)) is not None)
                members = index_members(root, found["rel"], found["pin"])
                kept = [m for m in members if not drop(" ".join(m["argv"]))]
                if not kept:
                    continue
                body = (json.dumps({"members": kept}, indent=2, sort_keys=True) + "\n").encode("utf-8")
                (root / found["rel"]).write_bytes(body)
                pin = hashlib.sha256(body).hexdigest()
                out.append(_repin(item, found["pin"], pin))
            else:
                out.append(drop_members(root, item, drop))
        return out
    if isinstance(node, dict):
        return {k: drop_members(root, v, drop) for k, v in node.items()}
    return node


def _repin(node: Any, old: str, new: str) -> Any:
    if isinstance(node, str):
        return node.replace(old, new)
    if isinstance(node, dict):
        return {k: _repin(v, old, new) for k, v in node.items()}
    return [_repin(v, old, new) for v in node] if isinstance(node, list) else node
