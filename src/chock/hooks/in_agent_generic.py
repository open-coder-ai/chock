"""Generic in-agent install: merge agentseam-rendered hook fragments into vendor configs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from chock import vendors
from chock.emit import write_generated_json
from chock.hooks.runtime_vendor import runtime_rel, vendor_runtime


def load_config(path: Path) -> dict:
    """The vendor's config file as a dict; a file that is not readable JSON is refused."""
    settings: dict = {}
    if path.exists():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                settings = loaded
        except (json.JSONDecodeError, OSError):
            msg = f"{path} is not readable JSON; leaving it untouched"
            raise ValueError(msg) from None
    return settings


def _marker(vendor: str) -> str:
    return runtime_rel(vendor).as_posix()


def _ours(node: Any, marker: str) -> bool:
    return marker in json.dumps(node)


def _collect_ours(node: Any, marker: str, into: dict[str, dict]) -> None:
    """Every list-borne entry of ours anywhere under `node`, keyed by its normalized form."""
    if isinstance(node, dict):
        for value in node.values():
            _collect_ours(value, marker, into)
    elif isinstance(node, list):
        for entry in node:
            if isinstance(entry, dict) and _ours(entry, marker):
                into[json.dumps(entry, sort_keys=True)] = entry


def _strip_ours(node: dict, marker: str) -> None:
    """Remove our entries in place; drop only keys that held nothing but ours."""
    for key in list(node):
        value = node[key]
        if isinstance(value, list):
            kept = [entry for entry in value if not _ours(entry, marker)]
            if kept:
                node[key] = kept
            elif kept != value:
                del node[key]
        elif isinstance(value, dict) and value:
            _strip_ours(value, marker)
            if not value:
                del node[key]


def _merge(settings: dict, fragment: dict) -> None:
    """Deep-merge one rendered fragment: append entries, keep the vendor's own keys."""
    for key, value in fragment.items():
        if isinstance(value, dict):
            if not isinstance(settings.get(key), dict):
                settings[key] = {}
            _merge(settings[key], value)
        elif isinstance(value, list):
            existing = settings.get(key)
            base = existing if isinstance(existing, list) else []
            settings[key] = base + list(value)
        else:
            settings.setdefault(key, value)


#: The compiled surfaces whose fragments are whole hook-config documents for this vendor.
#: Named rather than globbed over `*/`: a surface dir that happens to hold a like-named file
#: is not thereby something to merge into a vendor config.
FRAGMENT_SURFACES = ("pre-tool-use", "stop")


def _fragments(repo_root: Path, vendor: str) -> list[tuple[str, dict]]:
    compiled = repo_root / ".chock" / "compiled"
    globs = [f"*/{surface}/{vendor}-hooks.json" for surface in FRAGMENT_SURFACES]
    globs += [f"*/pre-tool-use/{vendor}-write-hooks.json", f"*/pre-tool-use/{vendor}-tool-call-hooks.json"]
    found: list[tuple[str, dict]] = []
    for path in sorted(path for glob in globs for path in compiled.glob(glob)):
        try:
            fragment = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if isinstance(fragment, dict):
            found.append((path.parent.parent.name, fragment))
    return found


def install_generic(repo_root: Path, vendor: str, *, uninstall: bool = False) -> list[str]:
    """Merge `vendor`'s compiled fragments into its recorded config file, keeping entries not ours.

    `uninstall=True` treats the vendor as having no fragments at all, the same as one whose
    compiled tree carries none -- see `install_merged`'s docstring for why `sync` needs this
    instead of relying on the compiled tree actually being empty.
    """
    repo_root = Path(repo_root)
    marker = _marker(vendor)
    fragments = [] if uninstall else _fragments(repo_root, vendor)
    config_path = repo_root / vendors.config_path(vendor)
    settings = load_config(config_path)
    prior: dict[str, dict] = {}
    _collect_ours(settings, marker, prior)
    _strip_ours(settings, marker)

    if not fragments:
        vendored = repo_root / runtime_rel(vendor)
        if vendored.exists():
            vendored.unlink()
        if config_path.exists() and prior:
            if settings:
                write_generated_json(config_path, settings)
            else:
                config_path.unlink()
        return []

    vendor_runtime(repo_root, vendor)
    for _policy_id, fragment in fragments:
        _merge(settings, fragment)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    write_generated_json(config_path, settings)
    return [policy_id for policy_id, _ in fragments]


def installed_generic_ids(repo_root: Path, vendor: str) -> set[str]:
    """Policy ids whose fragment entries are all present in `vendor`'s config file."""
    repo_root = Path(repo_root)
    marker = _marker(vendor)
    config_path = repo_root / vendors.config_path(vendor)
    if not config_path.exists():
        return set()
    try:
        settings = json.loads(config_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return set()
    present: dict[str, dict] = {}
    _collect_ours(settings if isinstance(settings, dict) else {}, marker, present)
    wanted_by: set[str] = set()
    missing: set[str] = set()
    for policy_id, fragment in _fragments(repo_root, vendor):
        wanted: dict[str, dict] = {}
        _collect_ours(fragment, marker, wanted)
        if wanted:
            wanted_by.add(policy_id)
        if not set(wanted) <= set(present):
            missing.add(policy_id)
    return wanted_by - missing
