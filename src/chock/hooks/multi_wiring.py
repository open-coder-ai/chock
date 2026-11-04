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
from chock.hooks.config_write import CONFIG_MODE
from chock.hooks.runtime_vendor import runtime_rel
from chock.manifest import CANONICAL_MANIFEST
from chock.policies import discover_policy_dirs
from chock.scaffold.mcp_write import remove_file, write_file

#: Where the pinned indexes live, one per (vendor, event, matcher): a path protect-agent-config guards, beside the runtimes.
INDEX_DIR = Path(".chock") / "bin" / "index"
#: The flags that make a hook command judge one policy: a member's argv starts at the first of them.
POLICY_FLAGS = ("--guard", "--gate", "--tool-call")
MULTI_FLAG, INDEX_SHA_FLAG = "--multi", "--index-sha256"
#: Seconds one member may take: the engine's own budget, as a single-policy hook has today.
MEMBER_SECONDS = ENGINE_BUDGET_SECONDS
#: Seconds the process needs beside its slowest member: reading the index, hashing, killing leftovers, logging.
GRACE_SECONDS = 5
_NO_COMMAND = "\0command\0"
_DERIVED_NAME = "agentseam"
_BYTECODE = ("__pycache__",)
_BYTECODE_SUFFIXES = (".pyc", ".pyo")
_MS_PER_SECOND = 1000
_COMPILED = (".chock", "compiled")


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


def _commands(node: Any) -> set[str]:
    """Every string a hook entry holds under a `command` key."""
    if isinstance(node, dict):
        own = {node["command"]} if isinstance(node.get("command"), str) else set()
        return own.union(*(_commands(v) for k, v in node.items() if k != "command"))
    return set().union(*(_commands(v) for v in node)) if isinstance(node, list) else set()


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


def _tree_files(root: Path, base: Path) -> dict[str, str]:
    """{posix path under `base`: sha256} of every file under `root` except bytecode."""
    found = {}
    for path in sorted(root.rglob("*")):
        if path.is_file() and not (set(path.parts) & set(_BYTECODE) or path.suffix in _BYTECODE_SUFFIXES):
            found[path.relative_to(base).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return found


def _pack_dir(repo_root: Path, target: Path) -> Path | None:
    """The policy folder a guard script sits in, or the one a compiled artifact was compiled from."""
    for parent in target.parents:
        if (repo_root / parent / CANONICAL_MANIFEST).is_file():
            return repo_root / parent
    parts = target.parts
    if parts[:2] == _COMPILED and len(parts) > len(_COMPILED):
        return next((d for d in discover_policy_dirs(repo_root) if d.name == parts[2]), None)
    return None


def member_files(repo_root: Path, argv: list[str]) -> dict[str, str] | None:
    """The sha256 of every file a single-policy entry for `argv` is verified by: its pack and its compiled tree.

    None when `argv` names no file chock can place, or the file is not among those: such an entry stays as it is.
    """
    root = Path(repo_root)
    target = Path(argv[1]) if len(argv) > 1 else None
    if target is None or target.is_absolute() or ".." in target.parts or not (root / target).is_file():
        return None
    pack = _pack_dir(root, target)
    if pack is None:
        return None
    files = _tree_files(pack, root)
    compiled = root.joinpath(*_COMPILED, pack.name)
    if compiled.is_dir():
        files.update(_tree_files(compiled, root))
    return files if target.as_posix() in files else None


def _quote(rel: str, *, quoted: bool) -> str:
    return f'"{rel}"' if quoted else rel


def _shape(node: Any) -> Any:
    """`node` without the names agentseam derives from a command: two entries that differ only there share a matcher."""
    if isinstance(node, dict):
        return {k: _shape(v) for k, v in node.items() if not (k == "name" and str(v).startswith(_DERIVED_NAME))}
    return [_shape(v) for v in node] if isinstance(node, list) else node


def _signature(entry: Any, old: str) -> str:
    return json.dumps(_shape(_replace(entry, old, _NO_COMMAND)), sort_keys=True)


class _Carrier(NamedTuple):
    """An entry that runs one policy: its command, the member it makes, and how its command is written."""

    entry: dict[str, Any]
    command: str
    argv: list[str]
    head: str
    quoted: bool
    files: dict[str, str]


class _Group:
    """The carriers sharing one signature, in the order they were found."""

    def __init__(self) -> None:
        self.carriers: list[_Carrier] = []


def _index_bytes(members: list[dict[str, Any]]) -> bytes:
    return (json.dumps({"members": members}, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _check_fits(vendor: str, entry: Any, argv: list[str]) -> bool:
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


def _carrier(repo_root: Path, vendor: str, entry: Any) -> _Carrier | None:
    """The member an entry that runs exactly one policy makes, else None (the entry stays as it is)."""
    if not isinstance(entry, dict):
        return None
    commands = _commands(entry)
    command = next(iter(commands)) if len(commands) == 1 else ""
    split = split_command(command, runtime_rel(vendor).as_posix())
    if split is None or not _check_fits(vendor, entry, split[1]):
        return None
    files = member_files(repo_root, split[1])
    return None if files is None else _Carrier(entry, command, split[1], split[0], split[2], files)


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
) -> list[Any]:
    """`entries` with every policy entry folded into one entry per identical shape; the pinned indexes are written.

    `rename(entry, command)` lets a vendor re-derive a field of the folded entry from its new command.
    """
    repo_root = Path(repo_root)
    groups: dict[str, _Group] = {}
    placed: list[Any] = []
    for entry in entries:
        found = _carrier(repo_root, vendor, entry) if eligible(entry) else None
        if found is None:
            placed.append(entry)
            continue
        group = groups.setdefault(_signature(entry, found.command), _Group())
        if not group.carriers:
            placed.append(group)
        group.carriers.append(found)
    return [
        _fold(repo_root, vendor, event, item, (kept, rename, write)) if isinstance(item, _Group) else item
        for item in placed
    ]


def _fold(repo_root: Path, vendor: str, event: str, group: _Group, how: tuple[set[str], Callable | None, bool]) -> Any:
    first = group.carriers[0]
    members = [{"argv": c.argv, "files": c.files, "timeout": MEMBER_SECONDS} for c in group.carriers]
    body = _index_bytes(members)
    pin = hashlib.sha256(body).hexdigest()
    slug = hashlib.sha256(_signature(first.entry, first.command).encode("utf-8")).hexdigest()[:8]
    rel = (INDEX_DIR / f"{vendor}-{event}-{slug}.json").as_posix()
    kept, rename, write = how
    if write:
        write_file(repo_root, rel, body, CONFIG_MODE)
    kept.add(rel)
    new = f"{first.head} {MULTI_FLAG} {_quote(rel, quoted=first.quoted)} {INDEX_SHA_FLAG} {pin}"
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
    for command in _commands(config):
        tokens = command.split(" ")
        if marker not in command or MULTI_FLAG not in tokens or INDEX_SHA_FLAG not in tokens:
            continue
        rel, pin = (tokens[tokens.index(flag) + 1].strip('"') for flag in (MULTI_FLAG, INDEX_SHA_FLAG))
        try:
            body = (root / rel).read_bytes()
            if hashlib.sha256(body).hexdigest() == pin:
                found.update(tuple(m["argv"]) for m in json.loads(body)["members"])
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return found


def member_installed(repo_root: Path, vendor: str, config: Any, entry: Any) -> bool:
    """Whether a per-policy `entry` is carried by a pinned index in `config` (the folded form of that entry)."""
    found = _carrier(Path(repo_root), vendor, entry)
    return found is not None and tuple(found.argv) in installed_members(repo_root, vendor, config)
