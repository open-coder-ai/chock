"""One installer for every in-agent hook surface; per-vendor wire facts from vendor config."""

from __future__ import annotations

import copy
import json
import re
import sys
from pathlib import Path
from typing import NamedTuple

from chock import vendors
from chock.compile.emitters.in_agent import AGENT_HOOKS_ENVELOPE, AGENT_HOOKS_EVENT, GENERIC_VENDORS
from chock.emit import write_generated_json
from chock.hooks.in_agent_generic import install_generic, installed_generic_ids
from chock.hooks.in_agent_generic import load_config as _load_config
from chock.hooks.runtime_vendor import runtime_rel, vendor_runtime

INTERPRETER_PLACEHOLDER = "@CHOCK_PYTHON@"

_COMMAND_TAIL_RE = re.compile(r'^.*?(?="\$\{CLAUDE_PROJECT_DIR\}[^"]*?/\.chock/bin/[a-z_]+\.py")')
_BIN_MARKER = "/.chock/bin/"


def _bake_interpreter(fragment: dict) -> dict:
    """A copy of `fragment` with the interpreter placeholder replaced by this machine's python."""
    exe = f'"{sys.executable}"'
    baked = copy.deepcopy(fragment)
    for hook in baked.get("hooks", []) or []:
        if isinstance(hook, dict) and isinstance(hook.get("command"), str):
            hook["command"] = hook["command"].replace(INTERPRETER_PLACEHOLDER, exe)
    return baked


def _normalize_fragment(fragment: dict) -> dict:
    """A copy of `fragment` with the interpreter token normalised to the placeholder."""
    normalized = copy.deepcopy(fragment)
    for hook in normalized.get("hooks", []) or []:
        command = hook.get("command") if isinstance(hook, dict) else None
        if isinstance(command, str) and _BIN_MARKER in command:
            hook["command"] = _COMMAND_TAIL_RE.sub(f"{INTERPRETER_PLACEHOLDER} ", command, count=1)
    return normalized


def _interpreter_runs_here(fragment: dict) -> bool:
    """Whether every baked interpreter in `fragment` still resolves on this machine."""
    for hook in fragment.get("hooks", []) or []:
        command = hook.get("command") if isinstance(hook, dict) else None
        if not isinstance(command, str) or _BIN_MARKER not in command:
            continue
        match = _COMMAND_TAIL_RE.match(command)
        if not match:
            continue
        interpreter = match.group(0).strip().strip('"')
        if not interpreter or interpreter == INTERPRETER_PLACEHOLDER:
            continue
        if not Path(interpreter).is_file():
            return False
    return True


class _Wiring(NamedTuple):
    """How one vendor's compiled fragments reach its config file; chock policy, not wire facts."""

    fragment_glob: str
    flat: bool
    unlink_runtime_when_empty: bool
    write_when_absent: bool
    report_key: str
    label: str


_MERGED = {
    "claude_code": _Wiring(
        fragment_glob="*/pre-tool-use/pretooluse.json",
        flat=False,
        unlink_runtime_when_empty=True,
        write_when_absent=True,
        report_key="matcher",
        label="PreToolUse hook(s) in .claude/settings.json",
    ),
    "cursor": _Wiring(
        fragment_glob="*/pre-tool-use/cursor-hooks.json",
        flat=True,
        unlink_runtime_when_empty=False,
        write_when_absent=False,
        report_key="command",
        label="Cursor hook entr(y/ies) in .cursor/hooks.json",
    ),
}

_OWNED_FILE_VENDOR = "vscode_copilot"
_OWNED_FILE_LABEL = "agent hook(s) in .github/hooks/chock.json"
_AGENT_HOOKS_GLOB = "*/agent-hooks/agent-hooks.json"

#: Vendors wired through chock's owned agent-hooks file rather than the vendor's config.
AGENT_HOOKS_VENDORS = (_OWNED_FILE_VENDOR,)

WIRED_VENDORS = (*_MERGED, *GENERIC_VENDORS, _OWNED_FILE_VENDOR)


def install_label(vendor: str) -> str:
    if vendor in _MERGED:
        return _MERGED[vendor].label
    if vendor in GENERIC_VENDORS:
        return f"hook entr(y/ies) in {vendors.config_path(vendor)}"
    return _OWNED_FILE_LABEL


def agent_hooks_rel(vendor: str = _OWNED_FILE_VENDOR) -> Path:
    """chock's own hooks file, beside the vendor's, in the directory the vendor reads."""
    return Path(vendors.config_path(vendor)).parent / "chock.json"


def _owned_marker(vendor: str) -> str:
    return f"/{runtime_rel(vendor).as_posix()}"


def _wrap(entry: dict) -> dict:
    return {"hooks": [copy.deepcopy(entry)]}


def _compiled_merged(repo_root: Path, vendor: str, event: str) -> list[dict]:
    """Compiled fragments (claude shape) or entries (cursor shape), ordered by policy id."""
    wiring = _MERGED[vendor]
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
            for entry in fragment.get(event, []) or []:
                if isinstance(entry, dict) and entry.get("command"):
                    found.append(entry)
        elif isinstance(fragment, dict) and fragment.get("hooks"):
            found.append(fragment)
    return found


def _install_merged(repo_root: Path, vendor: str) -> list[str]:
    """Merge compiled fragments into the vendor's config file, keeping entries not ours."""
    wiring = _MERGED[vendor]
    repo_root = Path(repo_root)
    event = vendors.shell_gate_event(vendor)
    wanted = _compiled_merged(repo_root, vendor, event)
    marker = _owned_marker(vendor)

    config_path = repo_root / vendors.config_path(vendor)
    settings = _load_config(config_path)
    hooks = settings.setdefault("hooks", {}) if isinstance(settings.get("hooks", {}), dict) else {}
    settings["hooks"] = hooks
    for key, value in vendors.config_envelope(vendor).items():
        settings.setdefault(key, value)

    def _is_ours(entry: dict) -> bool:
        if wiring.flat:
            return isinstance(entry, dict) and marker in str(entry.get("command", ""))
        inner = entry.get("hooks") if isinstance(entry, dict) else None
        if not isinstance(inner, list):
            return False
        return any(marker in str(h.get("command", "")) for h in inner if isinstance(h, dict))

    existing = hooks.get(event)
    ours_before = [e for e in existing if _is_ours(e)] if isinstance(existing, list) else []
    kept = [e for e in existing if not _is_ours(e)] if isinstance(existing, list) else []

    def _norm(entry: dict) -> dict:
        return _normalize_fragment(_wrap(entry))["hooks"][0] if wiring.flat else _normalize_fragment(entry)

    def _install_form(entry: dict) -> dict:
        target = _norm(entry)
        for installed in ours_before:
            runs = _interpreter_runs_here(_wrap(installed) if wiring.flat else installed)
            if _norm(installed) == target and runs:
                return installed
        return _bake_interpreter(_wrap(entry))["hooks"][0] if wiring.flat else _bake_interpreter(entry)

    if not wanted:
        if kept:
            hooks[event] = kept
        else:
            hooks.pop(event, None)
            if wiring.write_when_absent and not hooks:
                settings.pop("hooks", None)
        if wiring.unlink_runtime_when_empty:
            vendored = repo_root / runtime_rel(vendor)
            if vendored.exists():
                vendored.unlink()
        if not wiring.write_when_absent and not hooks and not config_path.exists():
            return []
    else:
        vendor_runtime(repo_root, vendor)
        hooks[event] = kept + [_install_form(entry) for entry in wanted]

    config_path.parent.mkdir(parents=True, exist_ok=True)
    write_generated_json(config_path, settings)
    return [entry.get(wiring.report_key, "?") for entry in wanted]


def _compiled_agent_hooks(repo_root: Path) -> dict[str, dict]:
    """Map policy id -> its compiled agent-hooks entry, ordered by policy id."""
    compiled = Path(repo_root) / ".chock" / "compiled"
    entries: dict[str, dict] = {}
    if not compiled.exists():
        return entries
    for path in sorted(compiled.glob(_AGENT_HOOKS_GLOB)):
        policy_id = path.parent.parent.name
        try:
            entry = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if isinstance(entry, dict) and entry.get("type") == "command":
            entries[policy_id] = entry
    return entries


def _install_agent_hooks(repo_root: Path) -> list[str]:
    """Rewrite chock's own agent-hooks file from compiled entries."""
    repo_root = Path(repo_root)
    entries = _compiled_agent_hooks(repo_root)
    dest = repo_root / agent_hooks_rel()
    if not entries:
        if dest.exists():
            dest.unlink()
        return []
    vendor_runtime(repo_root, _OWNED_FILE_VENDOR)
    doc = {**AGENT_HOOKS_ENVELOPE, "hooks": {AGENT_HOOKS_EVENT: [entries[pid] for pid in sorted(entries)]}}
    dest.parent.mkdir(parents=True, exist_ok=True)
    write_generated_json(dest, doc)
    return sorted(entries)


def install_hooks(repo_root: Path, vendor: str) -> list[str]:
    """Install `vendor`'s compiled in-agent hooks. Returns one item per entry installed."""
    if vendor in _MERGED:
        return _install_merged(repo_root, vendor)
    if vendor in GENERIC_VENDORS:
        return install_generic(repo_root, vendor)
    if vendor == _OWNED_FILE_VENDOR:
        return _install_agent_hooks(repo_root)
    msg = f"no in-agent wiring for vendor {vendor!r}; wired: {WIRED_VENDORS}"
    raise ValueError(msg)


def _installed_agent_hooks_entries(repo_root: Path) -> list[dict]:
    dest = Path(repo_root) / agent_hooks_rel()
    if not dest.exists():
        return []
    try:
        doc = json.loads(dest.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    hooks = doc.get("hooks") if isinstance(doc, dict) else None
    pre = hooks.get(AGENT_HOOKS_EVENT) if isinstance(hooks, dict) else None
    return [e for e in pre if isinstance(e, dict)] if isinstance(pre, list) else []


def installed_policy_ids(repo_root: Path, vendor: str) -> set[str]:
    """Policy ids whose compiled entries are actually present in `vendor`'s config file."""
    repo_root = Path(repo_root)
    if vendor in GENERIC_VENDORS:
        return installed_generic_ids(repo_root, vendor)
    if vendor == _OWNED_FILE_VENDOR:
        installed = _installed_agent_hooks_entries(repo_root)
        return {pid for pid, entry in _compiled_agent_hooks(repo_root).items() if entry in installed}

    wiring = _MERGED[vendor]
    event = vendors.shell_gate_event(vendor)
    config_path = repo_root / vendors.config_path(vendor)
    if not config_path.exists():
        return set()
    try:
        settings = json.loads(config_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return set()
    entries = (settings.get("hooks") or {}).get(event) if isinstance(settings, dict) else None
    if not isinstance(entries, list):
        return set()

    def _norm(entry: dict) -> dict:
        return _normalize_fragment(_wrap(entry))["hooks"][0] if wiring.flat else _normalize_fragment(entry)

    compiled = repo_root / ".chock" / "compiled"
    installed_ids: set[str] = set()
    for path in sorted(compiled.glob(wiring.fragment_glob)):
        try:
            fragment = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        wanted = [fragment] if not wiring.flat else list(fragment.get(event, []) or [])
        for candidate in wanted:
            target = _norm(candidate)
            if any(_norm(e) == target for e in entries if isinstance(e, dict)):
                installed_ids.add(path.parent.parent.name)
    return installed_ids
