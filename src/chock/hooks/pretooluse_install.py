"""Install compiled PreToolUse fragments into .claude/settings.json."""

from __future__ import annotations

import copy
import json
import re
import sys
from pathlib import Path

from chock.emit import write_generated_json
from chock.hooks.runtime_vendor import runtime_rel, vendor_runtime

SETTINGS_REL = Path(".claude") / "settings.json"
ADAPTER_REL = runtime_rel("claude_code")
_OWNED_MARKER = "/.chock/bin/claude_code.py"

INTERPRETER_PLACEHOLDER = "@CHOCK_PYTHON@"


def _bake_interpreter(fragment: dict) -> dict:
    """A copy of `fragment` with the interpreter placeholder replaced by this machine's python."""
    exe = f'"{sys.executable}"'
    baked = copy.deepcopy(fragment)
    for hook in baked.get("hooks", []) or []:
        if isinstance(hook, dict) and isinstance(hook.get("command"), str):
            hook["command"] = hook["command"].replace(INTERPRETER_PLACEHOLDER, exe)
    return baked


_COMMAND_TAIL_RE = re.compile(r'^.*?(?="\$\{CLAUDE_PROJECT_DIR\}[^"]*?/\.chock/bin/[a-z_]+\.py")')
_BIN_MARKER = "/.chock/bin/"


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


def vendor_adapter(repo_root: Path) -> Path:
    """Write the stdlib-only, agentseam-bundled Claude Code runtime into the consumer repo."""
    return vendor_runtime(repo_root, "claude_code")


def _compiled_fragments(repo_root: Path) -> list[dict]:
    """Every compiled PreToolUse fragment, ordered by policy id for determinism."""
    compiled = Path(repo_root) / ".chock" / "compiled"
    if not compiled.exists():
        return []
    fragments: list[dict] = []
    for path in sorted(compiled.glob("*/pre-tool-use/pretooluse.json")):
        try:
            fragment = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if isinstance(fragment, dict) and fragment.get("hooks"):
            fragments.append(fragment)
    return fragments


def _is_ours(entry: dict) -> bool:
    hooks = entry.get("hooks") if isinstance(entry, dict) else None
    if not isinstance(hooks, list):
        return False
    return any(_OWNED_MARKER in str(h.get("command", "")) for h in hooks if isinstance(h, dict))


def install_pretooluse_hooks(repo_root: Path) -> list[str]:
    """Merge compiled fragments into .claude/settings.json. Returns matchers installed."""
    repo_root = Path(repo_root)
    fragments = _compiled_fragments(repo_root)

    settings_path = repo_root / SETTINGS_REL
    settings: dict = {}
    if settings_path.exists():
        try:
            loaded = json.loads(settings_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                settings = loaded
        except (json.JSONDecodeError, OSError):
            raise ValueError(f"{settings_path} is not readable JSON; leaving it untouched") from None

    hooks = settings.setdefault("hooks", {}) if isinstance(settings.get("hooks", {}), dict) else {}
    settings["hooks"] = hooks
    existing = hooks.get("PreToolUse")
    ours_before = [e for e in existing if _is_ours(e)] if isinstance(existing, list) else []
    kept = [e for e in existing if not _is_ours(e)] if isinstance(existing, list) else []

    def _install_form(fragment: dict) -> dict:
        wanted = _normalize_fragment(fragment)
        for entry in ours_before:
            if _normalize_fragment(entry) == wanted and _interpreter_runs_here(entry):
                return entry
        return _bake_interpreter(fragment)

    if not fragments:
        vendored = repo_root / ADAPTER_REL
        if kept:
            hooks["PreToolUse"] = kept
        else:
            hooks.pop("PreToolUse", None)
            if not hooks:
                settings.pop("hooks", None)
        if vendored.exists():
            vendored.unlink()
    else:
        vendor_adapter(repo_root)
        hooks["PreToolUse"] = kept + [_install_form(f) for f in fragments]

    settings_path.parent.mkdir(parents=True, exist_ok=True)
    write_generated_json(settings_path, settings)
    return [f.get("matcher", "?") for f in fragments]


def installed_pretooluse_policy_ids(repo_root: Path) -> set[str]:
    """Policy ids whose compiled PreToolUse fragment is actually present in settings.json."""
    repo_root = Path(repo_root)
    settings_path = repo_root / SETTINGS_REL
    if not settings_path.exists():
        return set()
    try:
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return set()
    entries = (settings.get("hooks") or {}).get("PreToolUse") if isinstance(settings, dict) else None
    if not isinstance(entries, list):
        return set()

    compiled = repo_root / ".chock" / "compiled"
    installed: set[str] = set()
    for path in sorted(compiled.glob("*/pre-tool-use/pretooluse.json")):
        try:
            fragment = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        wanted = _normalize_fragment(fragment)
        if any(_normalize_fragment(e) == wanted for e in entries if isinstance(e, dict)):
            installed.add(path.parent.parent.name)
    return installed
