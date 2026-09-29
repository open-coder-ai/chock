"""One installer for every in-agent hook surface; per-vendor wire facts from vendor config."""

from __future__ import annotations

import json
from pathlib import Path

from chock import vendors
from chock.compile.emitters.in_agent import (
    AGENT_HOOKS_ENVELOPE,
    AGENT_HOOKS_EVENT,
    GATE_HOOKS_FILE,
    GENERIC_VENDORS,
)
from chock.emit import write_generated_json
from chock.hooks.in_agent_generic import install_generic, installed_generic_ids
from chock.hooks.in_agent_merged import MERGED, install_merged, installed_merged_ids
from chock.hooks.runtime_vendor import vendor_runtime

__all__ = [
    "AGENT_HOOKS_VENDORS",
    "WIRED_VENDORS",
    "agent_hooks_rel",
    "install_hooks",
    "install_label",
    "installed_policy_ids",
    "uninstall_hooks",
]

_OWNED_FILE_VENDOR = "vscode_copilot"
_OWNED_FILE_LABEL = "agent hook(s) in .github/hooks/chock.json"
_AGENT_HOOKS_GLOB = "*/agent-hooks/agent-hooks.json"
#: Compiled event maps for a content gate: its write gate, and its end-of-turn gate beside the stop gate.
_EVENT_MAP_GLOBS = (f"*/agent-hooks/{GATE_HOOKS_FILE}", f"*/stop/{_OWNED_FILE_VENDOR}-hooks.json")

#: Vendors wired through chock's owned agent-hooks file rather than the vendor's config.
#: Defined in `chock.vendors` because it caps what the stop surface may install too, and a
#: second copy here is the kind of hand-kept list this repository derives away.
AGENT_HOOKS_VENDORS = vendors.AGENT_HOOKS_VENDORS
assert _OWNED_FILE_VENDOR in AGENT_HOOKS_VENDORS  # noqa: S101 -- import-time invariant, not request handling

WIRED_VENDORS = (*MERGED, *GENERIC_VENDORS, _OWNED_FILE_VENDOR)


def install_label(vendor: str) -> str:
    if vendor in MERGED:
        return MERGED[vendor].label
    if vendor in GENERIC_VENDORS:
        return f"hook entr(y/ies) in {vendors.config_path(vendor)}"
    return _OWNED_FILE_LABEL


def agent_hooks_rel(vendor: str = _OWNED_FILE_VENDOR) -> Path:
    """chock's own hooks file, beside the vendor's, in the directory the vendor reads."""
    return Path(vendors.config_path(vendor)).parent / "chock.json"


def _read_entries(path: Path) -> list[dict]:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    return [doc] if isinstance(doc, dict) else []


def _event_entries(doc: dict) -> dict[str, list[dict]]:
    """`{event: [entry, ...]}` from a compiled event map, keeping only well-formed command entries."""
    found: dict[str, list[dict]] = {}
    for event, entries in doc.items():
        if isinstance(entries, list):
            kept = [e for e in entries if isinstance(e, dict) and e.get("type") == "command"]
            if kept:
                found[event] = kept
    return found


def _compiled_agent_hooks(repo_root: Path) -> dict[str, dict[str, list[dict]]]:
    """Map policy id -> its compiled entries by event, ordered by policy id.

    A guard policy compiles one bare entry (registered under the witnessed shell event); a content
    gate compiles event maps: the write gate under agent-hooks, the end-of-turn gate under stop.
    """
    compiled = Path(repo_root) / ".chock" / "compiled"
    entries: dict[str, dict[str, list[dict]]] = {}
    if not compiled.exists():
        return entries
    for path in sorted(compiled.glob(_AGENT_HOOKS_GLOB)):
        for entry in _read_entries(path):
            if entry.get("type") == "command":
                entries.setdefault(path.parent.parent.name, {}).setdefault(AGENT_HOOKS_EVENT, []).append(entry)
    for pattern in _EVENT_MAP_GLOBS:
        for path in sorted(compiled.glob(pattern)):
            for doc in _read_entries(path):
                for event, kept in _event_entries(doc).items():
                    entries.setdefault(path.parent.parent.name, {}).setdefault(event, []).extend(kept)
    return dict(sorted(entries.items()))


def _install_agent_hooks(repo_root: Path, *, uninstall: bool = False) -> list[str]:
    """Rewrite chock's own agent-hooks file from compiled entries."""
    repo_root = Path(repo_root)
    entries = {} if uninstall else _compiled_agent_hooks(repo_root)
    dest = repo_root / agent_hooks_rel()
    if not entries:
        if dest.exists():
            dest.unlink()
        return []
    vendor_runtime(repo_root, _OWNED_FILE_VENDOR)
    events: dict[str, list[dict]] = {}
    for by_event in entries.values():
        for event, kept in by_event.items():
            events.setdefault(event, []).extend(kept)
    doc = {**AGENT_HOOKS_ENVELOPE, "hooks": dict(sorted(events.items()))}
    dest.parent.mkdir(parents=True, exist_ok=True)
    write_generated_json(dest, doc)
    return sorted(entries)


def install_hooks(repo_root: Path, vendor: str) -> list[str]:
    """Install `vendor`'s compiled in-agent hooks. Returns one item per entry installed."""
    if vendor in MERGED:
        return install_merged(repo_root, vendor)
    if vendor in GENERIC_VENDORS:
        return install_generic(repo_root, vendor)
    if vendor == _OWNED_FILE_VENDOR:
        return _install_agent_hooks(repo_root)
    msg = f"no in-agent wiring for vendor {vendor!r}; wired: {WIRED_VENDORS}"
    raise ValueError(msg)


def uninstall_hooks(repo_root: Path, vendor: str) -> None:
    """Remove chock's entries for `vendor`, as if its compiled tree carried no fragments.

    Compiling is agent-agnostic -- a vendor `supported_agents` no longer names still gets its
    fragments compiled -- so `install_hooks` would find them and reinstall rather than remove.
    `sync` calls this for a vendor it no longer wires, before pruning its vendored runtime.
    """
    if vendor in MERGED:
        install_merged(repo_root, vendor, uninstall=True)
    elif vendor in GENERIC_VENDORS:
        install_generic(repo_root, vendor, uninstall=True)
    elif vendor == _OWNED_FILE_VENDOR:
        _install_agent_hooks(repo_root, uninstall=True)
    else:
        msg = f"no in-agent wiring for vendor {vendor!r}; wired: {WIRED_VENDORS}"
        raise ValueError(msg)


def _installed_agent_hooks_entries(repo_root: Path) -> dict[str, list[dict]]:
    dest = Path(repo_root) / agent_hooks_rel()
    if not dest.exists():
        return {}
    try:
        doc = json.loads(dest.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    hooks = doc.get("hooks") if isinstance(doc, dict) else None
    return _event_entries(hooks) if isinstance(hooks, dict) else {}


def installed_policy_ids(repo_root: Path, vendor: str) -> set[str]:
    """Policy ids whose compiled entries are actually present in `vendor`'s config file."""
    repo_root = Path(repo_root)
    if vendor in GENERIC_VENDORS:
        return installed_generic_ids(repo_root, vendor)
    if vendor == _OWNED_FILE_VENDOR:
        installed = _installed_agent_hooks_entries(repo_root)
        return {
            pid
            for pid, by_event in _compiled_agent_hooks(repo_root).items()
            if all(entry in installed.get(event, []) for event, kept in by_event.items() for entry in kept)
        }
    return installed_merged_ids(repo_root, vendor)
