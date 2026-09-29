"""Merging compiled fragments into a vendor's OWN config file, one event key at a time.

The two vendors here (claude, cursor) predate agentseam's rendering and keep hand-shaped
entries, so their install is a read-modify-write of a file the vendor also owns: chock's
entries are recognised by the vendored-runtime path inside them and replaced, everything
else in the file is left exactly as found. The generic half of the installer is
`in_agent_generic`; the file chock owns outright is in `in_agent_install`.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import NamedTuple

from chock import vendors
from chock.emit import write_generated_json
from chock.hooks.in_agent_generic import load_config as _load_config
from chock.hooks.runtime_vendor import owned_markers, runtime_rel, vendor_runtime


class Wiring(NamedTuple):
    """One (event key, fragment shape) pair a vendor's config file receives."""

    event: str
    fragment_glob: str
    flat: bool
    report_key: str


class VendorWiring(NamedTuple):
    """How one vendor's compiled fragments reach its config file; chock policy, not wire facts."""

    wirings: tuple[Wiring, ...]
    unlink_runtime_when_empty: bool
    write_when_absent: bool
    label: str


MERGED = {
    "claude_code": VendorWiring(
        wirings=(
            Wiring(
                event=vendors.shell_gate_event("claude_code"),
                # pretooluse*.json, not pretooluse.json: a policy contributes a shell entry, a
                # content entry, or both, and the merge loop already handles several fragments.
                fragment_glob="*/pre-tool-use/pretooluse*.json",
                flat=False,
                report_key="matcher",
            ),
            # The same settings file, a second event key. Held apart from the one above
            # rather than folded into its glob: entries under one event are not entries
            # under the other, and a merge that confused them would install a turn-end hook
            # as a pre-tool one.
            Wiring(
                event=vendors.stop_event("claude_code"),
                fragment_glob="*/stop/stop.json",
                flat=False,
                report_key="matcher",
            ),
        ),
        unlink_runtime_when_empty=True,
        write_when_absent=True,
        label="PreToolUse/Stop hook(s) in .claude/settings.json",
    ),
    "cursor": VendorWiring(
        wirings=(
            Wiring(
                event=vendors.shell_gate_event("cursor"),
                fragment_glob="*/pre-tool-use/cursor-hooks.json",
                flat=True,
                report_key="command",
            ),
            # The generic pre-tool event, a different key from the shell one above: a content
            # gate judges the file a Write would leave, the shell guard judges a command.
            Wiring(
                event=vendors.pre_tool_event("cursor"),
                fragment_glob="*/pre-tool-use/cursor-write-hooks.json",
                flat=True,
                report_key="command",
            ),
            Wiring(
                event=vendors.stop_event("cursor"),
                fragment_glob="*/stop/cursor-hooks.json",
                flat=True,
                report_key="command",
            ),
        ),
        unlink_runtime_when_empty=False,
        write_when_absent=False,
        label="Cursor hook entr(y/ies) in .cursor/hooks.json",
    ),
}


def _compiled(repo_root: Path, wiring: Wiring) -> list[dict]:
    """Compiled fragments (claude shape) or entries (cursor shape), ordered by policy id."""
    compiled = Path(repo_root) / ".chock" / "compiled"
    if not compiled.exists():
        return []
    found: list[dict] = []
    for path in sorted(compiled.glob(wiring.fragment_glob)):
        try:
            fragment = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if wiring.flat:
            for entry in fragment.get(wiring.event, []) or []:
                if isinstance(entry, dict) and entry.get("command"):
                    found.append(entry)
        elif isinstance(fragment, dict) and fragment.get("hooks"):
            found.append(fragment)
    return found


def _ours_under(entry: dict, wiring: Wiring, markers: tuple[str, ...]) -> bool:
    """Whether this installed entry is one chock put there, by the vendored-runtime path in it."""
    if wiring.flat:
        command = str(entry.get("command", "")) if isinstance(entry, dict) else ""
        return any(marker in command for marker in markers)
    inner = entry.get("hooks") if isinstance(entry, dict) else None
    if not isinstance(inner, list):
        return False
    commands = [str(h.get("command", "")) for h in inner if isinstance(h, dict)]
    return any(marker in command for marker in markers for command in commands)


def _merge_event(hooks: dict, wiring: Wiring, wanted: list[dict], markers: tuple[str, ...]) -> list[str]:
    """Replace chock's entries under one event key in place, keeping entries that are not ours."""
    existing = hooks.get(wiring.event)
    existing = existing if isinstance(existing, list) else []
    kept = [e for e in existing if not _ours_under(e, wiring, markers)]

    # Ours are replaced wholesale: an entry carries nothing machine-specific worth keeping.
    if wanted:
        hooks[wiring.event] = kept + [copy.deepcopy(entry) for entry in wanted]
    elif kept:
        hooks[wiring.event] = kept
    else:
        hooks.pop(wiring.event, None)
    # The event name, for an entry shape that carries no matcher to report: a stop hook
    # matches nothing by design, and "?" reads as a defect rather than as that.
    return [entry.get(wiring.report_key) or wiring.event for entry in wanted]


def install_merged(repo_root: Path, vendor: str, *, uninstall: bool = False) -> list[str]:
    """Merge compiled fragments into the vendor's config file, keeping entries not ours.

    `uninstall=True` treats every wiring as wanting nothing, the same as a vendor whose
    compiled tree carries no fragments for it -- chock's entries come out (or the file goes,
    if it held only chock's) regardless of what is actually compiled. `sync` uses this for a
    vendor `supported_agents` no longer names, whose fragments are still compiled (compiling
    is agent-agnostic; only which vendors get installed is not) and would otherwise be
    reinstalled by the ordinary compiled-fragment lookup below.
    """
    vendor_wiring = MERGED[vendor]
    repo_root = Path(repo_root)
    markers = owned_markers(vendor)

    config_path = repo_root / vendors.config_path(vendor)
    settings = _load_config(config_path)
    hooks = settings.setdefault("hooks", {}) if isinstance(settings.get("hooks", {}), dict) else {}
    settings["hooks"] = hooks
    for key, value in vendors.config_envelope(vendor).items():
        settings.setdefault(key, value)

    reported: list[str] = []
    installed_any = False
    for wiring in vendor_wiring.wirings:
        wanted = [] if uninstall else _compiled(repo_root, wiring)
        installed_any = installed_any or bool(wanted)
        reported.extend(_merge_event(hooks, wiring, wanted, markers))

    if installed_any or _runtime_referenced(hooks, vendor):
        vendor_runtime(repo_root, vendor)
    else:
        if not hooks and vendor_wiring.write_when_absent:
            settings.pop("hooks", None)
        if vendor_wiring.unlink_runtime_when_empty:
            vendored = repo_root / runtime_rel(vendor)
            if vendored.exists():
                vendored.unlink()
        if not vendor_wiring.write_when_absent and not hooks and not config_path.exists():
            return []

    config_path.parent.mkdir(parents=True, exist_ok=True)
    write_generated_json(config_path, settings)
    return reported


def _runtime_referenced(hooks: dict, vendor: str) -> bool:
    """Whether any entry under any event key still runs this vendor's runtime.

    The session-start arm hook shares `claude_code.py` with the pre-tool and stop entries and
    is installed by a different installer. A repo with no in-agent fragments still has that
    hook, so unlinking the runtime for want of fragments left it pointing at nothing.
    """
    return runtime_rel(vendor).as_posix() in json.dumps(hooks)


def installed_merged_ids(repo_root: Path, vendor: str) -> set[str]:
    """Policy ids whose compiled entries are all present, under every event key chock wires here."""
    repo_root = Path(repo_root)
    config_path = repo_root / vendors.config_path(vendor)
    if not config_path.exists():
        return set()
    try:
        settings = json.loads(config_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return set()
    hooks = (settings.get("hooks") or {}) if isinstance(settings, dict) else {}
    if not isinstance(hooks, dict):
        return set()

    compiled = repo_root / ".chock" / "compiled"
    wanted_by: set[str] = set()
    missing: set[str] = set()
    for wiring in MERGED[vendor].wirings:
        entries = hooks.get(wiring.event)
        entries = entries if isinstance(entries, list) else []
        for path in sorted(compiled.glob(wiring.fragment_glob)):
            try:
                fragment = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            policy_id = path.parent.parent.name
            wanted = list(fragment.get(wiring.event, []) or []) if wiring.flat else [fragment]
            for candidate in wanted:
                wanted_by.add(policy_id)
                if not any(e == candidate for e in entries if isinstance(e, dict)):
                    missing.add(policy_id)
    return wanted_by - missing
