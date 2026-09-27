"""Install the SessionStart arm hook into .claude/settings.json."""

from __future__ import annotations

import json
from pathlib import Path

from agentseam import contract as _contract

from chock import vendors
from chock.emit import write_generated_json
from chock.hooks.launch import hook_command
from chock.hooks.runtime_vendor import owned_markers, runtime_rel, vendor_runtime
from chock.output import warn

SETTINGS_REL = Path(vendors.config_path("claude_code"))
ARM_EVENT = vendors.wire_event("claude_code", _contract.SESSION_START)
ADAPTER_REL = runtime_rel("claude_code")
_OWNED_MARKERS = owned_markers("claude_code")

ARM_FRAGMENT = {
    "hooks": [
        {
            "type": "command",
            "command": hook_command(ADAPTER_REL.as_posix()),
            "timeout": 300,
        }
    ]
}


def vendor_adapter(repo_root: Path) -> Path:
    """Write the stdlib-only, agentseam-bundled Claude Code runtime into the consumer repo."""
    return vendor_runtime(repo_root, "claude_code")


def _is_ours(entry: dict) -> bool:
    hooks = entry.get("hooks") if isinstance(entry, dict) else None
    if not isinstance(hooks, list):
        return False
    commands = [str(h.get("command", "")) for h in hooks if isinstance(h, dict)]
    return any(marker in command for marker in _OWNED_MARKERS for command in commands)


def install_sessionstart_hook(repo_root: Path) -> bool:
    """Ensure the arm hook is wired. Returns True when settings.json changed."""
    repo_root = Path(repo_root)
    settings_path = repo_root / SETTINGS_REL
    settings: dict = {}
    if settings_path.exists():
        try:
            loaded = json.loads(settings_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                settings = loaded
        except (json.JSONDecodeError, OSError):
            msg = f"{settings_path} is not readable JSON; leaving it untouched"
            raise ValueError(msg) from None

    hooks = settings.setdefault("hooks", {}) if isinstance(settings.get("hooks", {}), dict) else {}
    settings["hooks"] = hooks
    existing = hooks.get(ARM_EVENT)
    kept = [e for e in existing if not _is_ours(e)] if isinstance(existing, list) else []

    vendor_adapter(repo_root)

    desired = [*kept, json.loads(json.dumps(ARM_FRAGMENT))]
    if isinstance(existing, list) and desired == existing:
        return False
    hooks[ARM_EVENT] = desired
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    write_generated_json(settings_path, settings)
    return True


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - thin CLI shim
    root = Path(argv[0]) if argv else Path.cwd()
    try:
        changed = install_sessionstart_hook(root)
    except ValueError as exc:
        warn(str(exc))
        return 1
    print("SessionStart arm hook " + ("installed" if changed else "already current"))
    return 0
