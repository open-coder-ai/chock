"""Install the SessionStart arm hook into .claude/settings.json.

Git never clones hooks, so a fresh clone of a Chock repo enforces nothing at commit
time until `chock sync` runs. The SessionStart hook closes that gap for Claude Code:
the committed settings.json (consented through the workspace-trust prompt) runs the
vendored `.chock/bin/claude_code.py` (agentseam's bundle plus chock's own handler -- see
`gate/runtime_bundle.py`) when a session opens, which arms the git hooks
or tells the agent the one command that will.

This is repo wiring, not a policy surface: it is installed whenever hooks are wired,
carries no coverage claim, and one entry serves the whole repo. The committed-file
discipline is shared with `pretooluse_install`: only Chock-owned entries are touched
(identified by the adapter path in the command), the fragment carries the interpreter
placeholder, and an installed entry that is this fragment under another machine's
interpreter is kept byte-for-byte rather than re-baked into diff churn.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from chock.emit import write_generated_json
from chock.hooks.pretooluse_install import (
    INTERPRETER_PLACEHOLDER,
    SETTINGS_REL,
    _bake_interpreter,
    _normalize_fragment,
)
from chock.hooks.runtime_vendor import runtime_rel, vendor_runtime

ADAPTER_REL = runtime_rel("claude_code")
# Every Chock-owned SessionStart command contains this; nothing else should. Same file
# `pretooluse_install` vendors -- claude_code's bundled runtime handles both branches.
_OWNED_MARKER = "/.chock/bin/claude_code.py"

#: The one entry this module manages. `timeout` covers a full `chock sync` on a large
#: repo; the adapter's own subprocess timeout is shorter, so the hook still returns
#: (with the manual instruction) rather than being killed mid-print. No `--guard`: that
#: argument is what routes the bundled runtime's `handle()` to its pre_tool branch: absent,
#: a SessionStart event falls through to the session_start branch instead.
ARM_FRAGMENT = {
    "hooks": [
        {
            "type": "command",
            "command": f'{INTERPRETER_PLACEHOLDER} "${{CLAUDE_PROJECT_DIR}}/.chock/bin/claude_code.py"',
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
    return any(_OWNED_MARKER in str(h.get("command", "")) for h in hooks if isinstance(h, dict))


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
            # Refuse to overwrite a file we cannot parse: it is the adopter's, and a
            # rewrite would silently discard whatever they had in it.
            raise ValueError(f"{settings_path} is not readable JSON; leaving it untouched") from None

    hooks = settings.setdefault("hooks", {}) if isinstance(settings.get("hooks", {}), dict) else {}
    settings["hooks"] = hooks
    existing = hooks.get("SessionStart")
    ours_before = [e for e in existing if _is_ours(e)] if isinstance(existing, list) else []
    kept = [e for e in existing if not _is_ours(e)] if isinstance(existing, list) else []

    wanted = _normalize_fragment(ARM_FRAGMENT)
    install_form = None
    for entry in ours_before:
        if _normalize_fragment(entry) == wanted:
            install_form = entry  # same hook under another interpreter: keep it byte-for-byte
            break
    if install_form is None:
        install_form = _bake_interpreter(ARM_FRAGMENT)

    vendor_adapter(repo_root)

    desired = kept + [install_form]
    if isinstance(existing, list) and desired == existing:
        return False
    hooks["SessionStart"] = desired
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    write_generated_json(settings_path, settings)
    return True


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - thin CLI shim
    root = Path(argv[0]) if argv else Path.cwd()
    try:
        changed = install_sessionstart_hook(root)
    except ValueError as exc:
        print(f"[WARN] {exc}", file=sys.stderr)
        return 1
    print("SessionStart arm hook " + ("installed" if changed else "already current"))
    return 0
