"""Generic in-agent install: merge agentseam-rendered hook fragments into vendor configs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from chock import vendors
from chock.hooks import config_write, heartbeat, launch, stop_check
from chock.hooks.in_agent_toml import install_toml, installed_toml_ids
from chock.hooks.runtime_vendor import runtime_rel, vendor_runtime

_TOML = "toml"
#: The stop check's place in the fragment list: wired for every vendor, never reported as a policy.
STOP_CHECK_ID = "chock-stop"


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
            if not node[key]:
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


def _fragments(repo_root: Path, vendor: str) -> list[tuple[str, Any]]:
    compiled = repo_root / ".chock" / "compiled"
    globs = [f"*/{surface}/{vendor}-hooks.json" for surface in FRAGMENT_SURFACES]
    globs += [f"*/pre-tool-use/{vendor}-write-hooks.json", f"*/pre-tool-use/{vendor}-tool-call-hooks.json"]
    found: list[tuple[str, Any]] = []
    for path in sorted(path for glob in globs for path in compiled.glob(glob)):
        try:
            fragment = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if isinstance(fragment, dict) or (isinstance(fragment, list) and vendors.config_format(vendor) == _TOML):
            found.append((path.parent.parent.name, fragment))
    return found


def quote_free(vendor: str) -> bool:
    """Whether sync writes `vendor`'s commands quote-free: the rule and store data its plugin follows (hook_dir.quote_free)."""
    from chock.plugin import hook_dir  # noqa: PLC0415 -- the plugin side imports this package
    from chock.plugin.clients import CLIENTS  # noqa: PLC0415 -- likewise

    return any(client.agent == vendor and hook_dir.quote_free(name) for name, client in CLIENTS.items())


def windows_form(node: Any) -> Any:
    """`node` with every hook `command` in its quote-free form (launch.hook_command_quote_free)."""
    if isinstance(node, dict):
        return {
            k: launch.hook_command_quote_free(v) if k == "command" and isinstance(v, str) else windows_form(v)
            for k, v in node.items()
        }
    return [windows_form(v) for v in node] if isinstance(node, list) else node


def _for_runner(vendor: str, docs: list[tuple[str, Any]]) -> list[tuple[str, Any]]:
    """`docs` in the command form `vendor`'s hook runner reads on this machine."""
    return [(name, windows_form(doc)) for name, doc in docs] if quote_free(vendor) else docs


def _sync_runtime(repo_root: Path, vendor: str, *, wanted: bool) -> None:
    """Vendor `vendor`'s runtime while a hook entry runs it; otherwise drop it."""
    if wanted:
        vendor_runtime(repo_root, vendor)
        return
    vendored = repo_root / runtime_rel(vendor)
    if vendored.exists():
        vendored.unlink()


def install_generic(repo_root: Path, vendor: str, *, uninstall: bool = False) -> list[str]:
    """Merge `vendor`'s compiled fragments into its recorded config file, keeping entries not ours.

    `uninstall=True` treats the vendor as having no fragments at all, the same as one whose
    compiled tree carries none -- see `install_merged`'s docstring for why `sync` needs this
    instead of relying on the compiled tree actually being empty.
    """
    repo_root = Path(repo_root)
    config_rel = Path(vendors.config_path(vendor))
    config_write.check_unlinked(repo_root, config_rel)
    marker = _marker(vendor)
    fragments = [] if uninstall else _fragments(repo_root, vendor)
    stopping = [(STOP_CHECK_ID, stop_check.generic_doc(vendor))] if fragments else []
    if vendors.config_format(vendor) == _TOML:
        installed = install_toml(repo_root, vendor, [*fragments, *stopping])
        _sync_runtime(repo_root, vendor, wanted=bool(installed))
        return [policy_id for policy_id in installed if policy_id != STOP_CHECK_ID]
    config_path = repo_root / config_rel
    settings = load_config(config_path)
    prior: dict[str, dict] = {}
    _collect_ours(settings, marker, prior)
    _strip_ours(settings, marker)

    if not fragments:
        _sync_runtime(repo_root, vendor, wanted=False)
        if config_path.exists() and prior:
            if settings:
                config_write.write_json(repo_root, config_rel, settings)
            else:
                config_write.remove(repo_root, config_rel)
        return []

    vendor_runtime(repo_root, vendor)
    beat = heartbeat.sync_doc(vendor)
    beats = [("heartbeat", beat)] if isinstance(beat, dict) else []
    for _policy_id, fragment in _for_runner(vendor, [*fragments, *stopping, *beats]):
        _merge(settings, fragment)
    config_write.write_json(repo_root, config_rel, settings)
    return [policy_id for policy_id, _ in fragments]


def installed_generic_ids(repo_root: Path, vendor: str) -> set[str]:
    """Policy ids whose fragment entries are all present in `vendor`'s config file."""
    repo_root = Path(repo_root)
    if vendors.config_format(vendor) == _TOML:
        return installed_toml_ids(repo_root, vendor, _fragments(repo_root, vendor))
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
    for policy_id, fragment in _for_runner(vendor, _fragments(repo_root, vendor)):
        wanted: dict[str, dict] = {}
        _collect_ours(fragment, marker, wanted)
        if wanted:
            wanted_by.add(policy_id)
        if not set(wanted) <= set(present):
            missing.add(policy_id)
    return wanted_by - missing
