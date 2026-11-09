"""One hook entry per (event, matcher): the per-policy entries of a vendor config folded into a pinned policy index."""

from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any, NamedTuple

from chock.compile.emitters.in_agent_hooks import VENDOR_TIMEOUTS
from chock.gate.budget import ENGINE_BUDGET_SECONDS
from chock.gate.guard_runner import PYTHON_SUFFIX
from chock.gate.multi import sha256_of
from chock.gate.runner.halt import HALT_HOOK_FLAG
from chock.hooks.config_write import CONFIG_MODE
from chock.hooks.multi_members import member_files
from chock.hooks.runtime_vendor import runtime_rel
from chock.scaffold.mcp_write import remove_file, write_file

#: Where the pinned indexes live, one per (vendor, event, matcher): a path protect-agent-config guards, beside the runtimes.
INDEX_DIR = Path(".chock") / "bin" / "index"
#: The flags that make a hook command judge one policy: a member's argv starts at the first of them.
POLICY_FLAGS = ("--guard", "--gate", "--tool-call")
MULTI_FLAG, INDEX_SHA_FLAG, ROOT_FLAG = "--multi", "--index-sha256", "--root"
PLUGIN_INDEX_DIR = "scripts/chock_index"  # where a plugin's pinned indexes sit in the package, beside its scripts
#: Seconds one member may take: the engine's own budget, as a single-policy hook has today.
MEMBER_SECONDS = ENGINE_BUDGET_SECONDS
#: Seconds the process needs beside its slowest member: reading the index, hashing, killing leftovers, logging.
GRACE_SECONDS = 5
_NO_COMMAND = "\0command\0"
_DERIVED_NAME = "agentseam"
_MS_PER_SECOND = 1000


class IndexRefusalError(RuntimeError):
    """A member cannot finish inside the vendor entry's timeout: refused, never installed."""


def split_command(command: str, marker: str) -> tuple[str, list[str], bool] | None:
    """(head up to the runtime, the member's argv, whether its paths are quoted) of a command judging one policy."""
    words = command.split(" ")
    for i, word in enumerate(words):
        if i and word in POLICY_FLAGS and marker in words[i - 1] and words[i - 1].strip('"').endswith(PYTHON_SUFFIX):
            tail = words[i:]
            return " ".join(words[:i]), [w.strip('"') for w in tail], len(tail) > 1 and tail[1].startswith('"')
    return None


def commands(node: Any) -> set[str]:
    """Every string a hook entry holds under a `command` key."""
    if isinstance(node, dict):
        own = {node["command"]} if isinstance(node.get("command"), str) else set()
        return own.union(*(commands(v) for k, v in node.items() if k != "command"))
    return set().union(*(commands(v) for v in node)) if isinstance(node, list) else set()


def _replace(node: Any, old: str, new: str) -> Any:
    """`node` with `old` replaced by `new` in every string it holds."""
    if isinstance(node, str):
        return node.replace(old, new)
    if isinstance(node, dict):
        return {k: _replace(v, old, new) for k, v in node.items()}
    return [_replace(v, old, new) for v in node] if isinstance(node, list) else node


def _timeout_seconds(vendor: str, entry: Any) -> float | None:
    """The timeout the vendor will enforce on this entry, in seconds; None where nothing documents one."""
    found: list[float] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            found.extend(
                float(v) for k, v in node.items() if k in ("timeoutSec", "timeout") and isinstance(v, int | float)
            )
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(entry)
    facts = VENDOR_TIMEOUTS.get(vendor)
    if found:
        return min(found) / (_MS_PER_SECOND if facts and facts["unit"] == "ms" else 1)
    return float(facts["default_seconds"]) if facts and facts["default_seconds"] else None


def _quote(rel: str, *, quoted: bool) -> str:
    return f'"{rel}"' if quoted else rel


def _shape(node: Any) -> Any:
    """`node` without the names agentseam derives from a command: two entries that differ only there share a matcher."""
    if isinstance(node, dict):
        return {k: _shape(v) for k, v in node.items() if not (k == "name" and str(v).startswith(_DERIVED_NAME))}
    return [_shape(v) for v in node] if isinstance(node, list) else node


def _signature(entry: Any, old: str) -> str:
    return json.dumps(_shape(_replace(entry, old, _NO_COMMAND)), sort_keys=True)


class Carrier(NamedTuple):
    """An entry that runs one policy: its command, the member it makes, and how its command is written."""

    entry: dict[str, Any]
    command: str
    argv: list[str]
    head: str
    quoted: bool
    files: dict[str, str]
    root: str | None = None  # a plugin's root text, as its commands carry it; None in a repo
    member: str | None = None


class _Group:
    """The carriers sharing one signature, in the order they were found; `stop` once the stop check is folded in."""

    def __init__(self) -> None:
        self.carriers: list[Carrier] = []
        self.stop = False


def stop_runtime(entry: Any) -> str | None:
    """The launcher-and-runtime text of a standalone stop-check entry (`<runtime> --stop-check`), else None."""
    found = commands(entry) if isinstance(entry, dict) else set()
    command = next(iter(found)) if len(found) == 1 else ""
    body, sep, rest = command.rpartition(f" {HALT_HOOK_FLAG}")
    return body if sep and body and not rest and MULTI_FLAG not in command.split(" ") else None


def _takes_stop(group: _Group, entry: Any, body: str) -> bool:
    """Whether `group` matches every tool the stop entry does (same shape) and runs the same runtime after its launcher."""
    first = group.carriers[0]
    prefix, _, runtime = body.rpartition(" ")
    wrapped = bool(prefix) and first.head.startswith(f"{prefix} ") and first.head.endswith(f" {runtime}")
    same_runtime = first.head == body or wrapped
    return same_runtime and _signature(entry, f"{body} {HALT_HOOK_FLAG}") == _signature(first.entry, first.command)


def _fold_stop(placed: list[Any], eligible: Callable[[Any], bool]) -> list[Any]:
    """`placed` with the standalone stop check folded into the catch-all group, if one exists; else as it was."""
    for at, item in enumerate(placed):
        body = None if isinstance(item, _Group) or not eligible(item) else stop_runtime(item)
        if body is None:
            continue
        group = next((g for g in placed if isinstance(g, _Group) and _takes_stop(g, item, body)), None)
        if group is not None:
            group.stop = True
            return placed[:at] + placed[at + 1 :]
    return placed


def _index_bytes(members: list[dict[str, Any]]) -> bytes:
    return (json.dumps({"members": members}, indent=2, sort_keys=True) + "\n").encode("utf-8")


def check_fits(vendor: str, entry: Any, argv: list[str]) -> bool:
    """Whether a member and the grace fit the entry's timeout; refuses one that cannot, False where no timeout is known."""
    allowed = _timeout_seconds(vendor, entry)
    if allowed is None:
        return False
    if allowed < MEMBER_SECONDS + GRACE_SECONDS:
        msg = (
            f"{vendor}: {' '.join(argv)} may take {MEMBER_SECONDS}s and the process needs {GRACE_SECONDS}s beside it, "
            f"but the hook entry's timeout is {allowed:g}s; the client would cut the process off and let the call through"
        )
        raise IndexRefusalError(msg)
    return True


def _carrier(repo_root: Path, vendor: str, entry: Any) -> Carrier | None:
    """The member an entry that runs exactly one policy makes, else None (the entry stays as it is)."""
    if not isinstance(entry, dict):
        return None
    found_commands = commands(entry)
    command = next(iter(found_commands)) if len(found_commands) == 1 else ""
    split = split_command(command, runtime_rel(vendor).as_posix())
    if split is None or not check_fits(vendor, entry, split[1]):
        return None
    files = member_files(repo_root, split[1])
    return None if files is None else Carrier(entry, command, split[1], split[0], split[2], files)


def collapse_list(  # noqa: PLR0913 -- the five places an entry list is folded each pass their own rename, eligibility and dry-run choice
    repo_root: Path,
    vendor: str,
    event: str,
    entries: list[Any],
    kept: set[str],
    *,
    rename: Callable[[Any, str], Any] | None = None,
    write: bool = True,
    eligible: Callable[[Any], bool] = lambda _entry: True,
    carry: Callable[[Any], Carrier | None] | None = None,
    sink: Callable[[str, bytes], None] | None = None,
) -> list[Any]:
    """`entries` with every policy entry folded into one entry per identical shape; the pinned indexes are written.

    A standalone stop-check entry is folded into the group with its own shape and runtime (`--stop-check` on the
    multi command), so the multi process checks the stop first; with no such group it stays as it is.

    `rename(entry, command)` lets a vendor re-derive a field of the folded entry from its new command; a plugin's
    `carry` makes the member of an entry from its package, and `sink` takes the index files it would write.
    """
    repo_root = Path(repo_root)
    groups: dict[str, _Group] = {}
    placed: list[Any] = []
    for entry in entries:
        found = (carry(entry) if carry else _carrier(repo_root, vendor, entry)) if eligible(entry) else None
        if found is None:
            placed.append(entry)
            continue
        group = groups.setdefault(_signature(entry, found.command) + (found.head if found.root else ""), _Group())
        if not group.carriers:
            placed.append(group)
        group.carriers.append(found)
    placed = _fold_stop(placed, eligible)
    return [
        _fold(repo_root, vendor, event, item, (kept, rename, write, sink)) if isinstance(item, _Group) else item
        for item in placed
    ]


def _fold(repo_root: Path, vendor: str, event: str, group: _Group, how: tuple[Any, ...]) -> Any:
    first = group.carriers[0]
    members = [{"argv": c.argv, "files": c.files, "timeout": MEMBER_SECONDS} for c in group.carriers]
    members = [m | ({"member": c.member} if c.member else {}) for m, c in zip(members, group.carriers, strict=True)]
    body = _index_bytes(members)
    pin = hashlib.sha256(body).hexdigest()
    slug = hashlib.sha256(_signature(first.entry, first.command).encode("utf-8")).hexdigest()[:8]
    kept, rename, write, sink = how
    if first.root is None:
        rel = (INDEX_DIR / f"{vendor}-{event}-{slug}.json").as_posix()
        if write:
            write_file(repo_root, rel, body, CONFIG_MODE)
        kept.add(rel)
        tail = f"{MULTI_FLAG} {_quote(rel, quoted=first.quoted)} {INDEX_SHA_FLAG} {pin}"
    else:
        rel = f"{PLUGIN_INDEX_DIR}/{event}-{slug}.json"
        if sink:
            sink(rel, body)
        index, root = (_quote(text, quoted=first.quoted) for text in (f"{first.root}/{rel}", first.root))
        tail = f"{MULTI_FLAG} {index} {INDEX_SHA_FLAG} {pin} {ROOT_FLAG} {root}"
    new = f"{first.head} {tail}" + (f" {HALT_HOOK_FLAG}" if group.stop else "")
    folded = copy.deepcopy(_replace(first.entry, first.command, new))
    return rename(folded, new) if rename is not None else folded


def prune(repo_root: Path, vendor: str, kept: set[str]) -> None:
    """Remove this vendor's indexes that no entry references any more."""
    folder = Path(repo_root) / INDEX_DIR
    for path in sorted(folder.glob(f"{vendor}-*.json")) if folder.is_dir() else []:
        rel = path.relative_to(repo_root).as_posix()
        if rel not in kept:
            remove_file(Path(repo_root), rel)


def collapse_events(repo_root: Path, vendor: str, hooks: Any, events: tuple[str, ...], kept: set[str]) -> None:
    """Fold, in place, the entry list under every key of `events` found anywhere in `hooks`."""
    if isinstance(hooks, dict):
        for key, value in list(hooks.items()):
            if key in events and isinstance(value, list):
                hooks[key] = collapse_list(repo_root, vendor, key, value, kept)
            else:
                collapse_events(repo_root, vendor, value, events, kept)
    elif isinstance(hooks, list):
        for value in hooks:
            collapse_events(repo_root, vendor, value, events, kept)


def installed_members(repo_root: Path, vendor: str, config: Any) -> set[tuple[str, ...]]:
    """The argv of every member of a pinned index an entry of `config` runs, whose file is there and matches its pin."""
    root, marker, found = Path(repo_root), runtime_rel(vendor).as_posix(), set()
    for command in commands(config):
        tokens = command.split(" ")
        if marker not in command or MULTI_FLAG not in tokens or INDEX_SHA_FLAG not in tokens:
            continue
        rel, pin = (tokens[tokens.index(flag) + 1].strip('"') for flag in (MULTI_FLAG, INDEX_SHA_FLAG))
        try:
            if sha256_of(root / rel) == pin:
                found.update(tuple(m["argv"]) for m in json.loads((root / rel).read_bytes())["members"])
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return found


def member_installed(repo_root: Path, vendor: str, config: Any, entry: Any) -> bool:
    """Whether a per-policy `entry` is carried by a pinned index in `config` (the folded form of that entry)."""
    found = _carrier(Path(repo_root), vendor, entry)
    return found is not None and tuple(found.argv) in installed_members(repo_root, vendor, config)
