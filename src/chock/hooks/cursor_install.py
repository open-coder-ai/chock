"""Install compiled Cursor hook fragments into .cursor/hooks.json."""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

from chock.emit import write_generated_json
from chock.hooks.pretooluse_install import (
    _bake_interpreter,
    _interpreter_runs_here,
    _normalize_fragment,
)
from chock.hooks.runtime_vendor import vendor_runtime

CURSOR_HOOKS_REL = Path(".cursor") / "hooks.json"
_EVENT = "beforeShellExecution"
_OWNED_MARKER = "/.chock/bin/cursor.py"


def vendor_adapter(repo_root: Path) -> Path:
    """Write the stdlib-only, agentseam-bundled Cursor runtime into the consumer repo."""
    return vendor_runtime(repo_root, "cursor")


def _wrap(entry: dict) -> dict:
    return {"hooks": [copy.deepcopy(entry)]}


def _bake_entry(entry: dict) -> dict:
    return _bake_interpreter(_wrap(entry))["hooks"][0]


def _normalize_entry(entry: dict) -> dict:
    return _normalize_fragment(_wrap(entry))["hooks"][0]


def _is_ours(entry: dict) -> bool:
    return isinstance(entry, dict) and _OWNED_MARKER in str(entry.get("command", ""))


def _compiled_entries(repo_root: Path) -> list[dict]:
    """Every compiled Cursor hook entry, ordered by policy id for determinism."""
    compiled = Path(repo_root) / ".chock" / "compiled"
    if not compiled.exists():
        return []
    entries: list[dict] = []
    for path in sorted(compiled.glob("*/pre-tool-use/cursor-hooks.json")):
        try:
            fragment = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        for entry in fragment.get(_EVENT, []) or []:
            if isinstance(entry, dict) and entry.get("command"):
                entries.append(entry)
    return entries


def install_cursor_hooks(repo_root: Path) -> list[str]:
    """Merge compiled entries into .cursor/hooks.json. Returns commands installed."""
    repo_root = Path(repo_root)
    wanted_entries = _compiled_entries(repo_root)

    hooks_path = repo_root / CURSOR_HOOKS_REL
    settings: dict = {}
    if hooks_path.exists():
        try:
            loaded = json.loads(hooks_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                settings = loaded
        except (json.JSONDecodeError, OSError):
            raise ValueError(f"{hooks_path} is not readable JSON; leaving it untouched") from None

    hooks = settings.setdefault("hooks", {}) if isinstance(settings.get("hooks", {}), dict) else {}
    settings["hooks"] = hooks
    settings.setdefault("version", 1)
    existing = hooks.get(_EVENT)
    ours_before = [e for e in existing if _is_ours(e)] if isinstance(existing, list) else []
    kept = [e for e in existing if not _is_ours(e)] if isinstance(existing, list) else []

    def _install_form(entry: dict) -> dict:
        wanted = _normalize_entry(entry)
        for installed in ours_before:
            if _normalize_entry(installed) == wanted and _interpreter_runs_here(_wrap(installed)):
                return installed
        return _bake_entry(entry)

    if not wanted_entries:
        if kept:
            hooks[_EVENT] = kept
        else:
            hooks.pop(_EVENT, None)
        if not hooks and not hooks_path.exists():
            return []
    else:
        vendor_adapter(repo_root)
        hooks[_EVENT] = kept + [_install_form(e) for e in wanted_entries]

    hooks_path.parent.mkdir(parents=True, exist_ok=True)
    write_generated_json(hooks_path, settings)
    return [e.get("command", "?") for e in wanted_entries]


def installed_cursor_policy_ids(repo_root: Path) -> set[str]:
    """Policy ids whose compiled Cursor entry is actually present in .cursor/hooks.json."""
    repo_root = Path(repo_root)
    hooks_path = repo_root / CURSOR_HOOKS_REL
    if not hooks_path.exists():
        return set()
    try:
        settings = json.loads(hooks_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return set()
    entries = (settings.get("hooks") or {}).get(_EVENT) if isinstance(settings, dict) else None
    if not isinstance(entries, list):
        return set()

    compiled = repo_root / ".chock" / "compiled"
    installed: set[str] = set()
    for path in sorted(compiled.glob("*/pre-tool-use/cursor-hooks.json")):
        try:
            fragment = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        for entry in fragment.get(_EVENT, []) or []:
            wanted = _normalize_entry(entry)
            if any(_normalize_entry(e) == wanted for e in entries if isinstance(e, dict)):
                installed.add(path.parent.parent.name)
    return installed


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - thin CLI shim
    root = Path(argv[0]) if argv else Path.cwd()
    try:
        commands = install_cursor_hooks(root)
    except ValueError as exc:
        print(f"[WARN] {exc}", file=sys.stderr)
        return 1
    print(f"Registered {len(commands)} Cursor hook entr(y/ies) in .cursor/hooks.json")
    return 0
