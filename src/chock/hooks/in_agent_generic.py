"""Generic in-agent install: merge agentseam-rendered hook fragments into vendor configs."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

from chock import vendors
from chock.emit import write_generated_json
from chock.hooks.runtime_vendor import runtime_rel, vendor_runtime

INTERPRETER_PLACEHOLDER = "@CHOCK_PYTHON@"

_INTERP_RE = re.compile(r'(^|&\s+)("[^"]+"|\S+)(?=\s+"\.chock/bin/)')


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


def _map_strings(node: Any, fn) -> Any:
    if isinstance(node, dict):
        return {key: _map_strings(value, fn) for key, value in node.items()}
    if isinstance(node, list):
        return [_map_strings(value, fn) for value in node]
    return fn(node) if isinstance(node, str) else node


def _bake(node: Any) -> Any:
    exe = f'"{sys.executable}"'
    return _map_strings(node, lambda s: s.replace(INTERPRETER_PLACEHOLDER, exe))


def _normalize(node: Any) -> Any:
    return _map_strings(node, lambda s: _INTERP_RE.sub(rf"\g<1>{INTERPRETER_PLACEHOLDER}", s))


def _norm_key(entry: dict) -> str:
    return json.dumps(_normalize(entry), sort_keys=True)


def _interpreter_runs(entry: dict) -> bool:
    """Whether every baked interpreter in `entry` still resolves on this machine."""
    stale = []

    def _probe(value: str) -> str:
        match = _INTERP_RE.search(value)
        if match:
            interpreter = match.group(2).strip('"')
            if interpreter != INTERPRETER_PLACEHOLDER and not Path(interpreter).is_file():
                stale.append(interpreter)
        return value

    _map_strings(entry, _probe)
    return not stale


def _collect_ours(node: Any, marker: str, into: dict[str, dict]) -> None:
    """Every list-borne entry of ours anywhere under `node`, keyed by its normalized form."""
    if isinstance(node, dict):
        for value in node.values():
            _collect_ours(value, marker, into)
    elif isinstance(node, list):
        for entry in node:
            if isinstance(entry, dict) and _ours(entry, marker):
                into[_norm_key(entry)] = entry


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


def _merge(settings: dict, fragment: dict, prior: dict[str, dict]) -> None:
    """Deep-merge one rendered fragment: append entries, keep the vendor's own keys."""
    for key, value in fragment.items():
        if isinstance(value, dict):
            if not isinstance(settings.get(key), dict):
                settings[key] = {}
            _merge(settings[key], value, prior)
        elif isinstance(value, list):
            existing = settings.get(key)
            base = existing if isinstance(existing, list) else []
            settings[key] = base + [_install_form(entry, prior) for entry in value]
        else:
            settings.setdefault(key, value)


def _install_form(entry: Any, prior: dict[str, dict]) -> Any:
    if not isinstance(entry, dict):
        return entry
    installed = prior.get(_norm_key(entry))
    if installed is not None and _interpreter_runs(installed):
        return installed
    return _bake(entry)


def _fragments(repo_root: Path, vendor: str) -> list[tuple[str, dict]]:
    found: list[tuple[str, dict]] = []
    for path in sorted((repo_root / ".chock" / "compiled").glob(f"*/pre-tool-use/{vendor}-hooks.json")):
        try:
            fragment = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if isinstance(fragment, dict):
            found.append((path.parent.parent.name, fragment))
    return found


def install_generic(repo_root: Path, vendor: str) -> list[str]:
    """Merge `vendor`'s compiled fragments into its recorded config file, keeping entries not ours."""
    repo_root = Path(repo_root)
    marker = _marker(vendor)
    fragments = _fragments(repo_root, vendor)
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
        _merge(settings, fragment, prior)
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
    installed: set[str] = set()
    for policy_id, fragment in _fragments(repo_root, vendor):
        wanted: dict[str, dict] = {}
        _collect_ours(fragment, marker, wanted)
        if wanted and set(wanted) <= set(present):
            installed.add(policy_id)
    return installed
