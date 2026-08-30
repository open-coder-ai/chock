"""Install compiled agent-hooks entries into `.github/hooks/chock.json`.

Copilot CLI and VS Code agent mode both read `.github/hooks/*.json`. `chock.json` is our
dedicated file -- we own it wholesale and rewrite it on every sync -- so there is no merge
with a user's own hooks (those live in other `.github/hooks/*.json` files).

Coverage witness, same discipline as PreToolUse: a policy is credited `enforced` on
copilot/vscode only when its compiled entry byte-matches an entry actually present in the
installed file. Editing the guard changes the compiled entry, which no longer matches what
is installed, so the claim drops until the file is re-synced -- what is wired up is the old
entry.
"""

from __future__ import annotations

import json
from pathlib import Path

from chock.emit import write_generated_json
from chock.hooks.runtime_vendor import vendor_runtime

HOOKS_REL = Path(".github") / "hooks" / "chock.json"
_COMPILED_GLOB = "*/agent-hooks/agent-hooks.json"


def _compiled_entries(repo_root: Path) -> dict[str, dict]:
    """Map policy id -> its compiled agent-hooks entry, ordered by policy id."""
    compiled = Path(repo_root) / ".chock" / "compiled"
    entries: dict[str, dict] = {}
    if not compiled.exists():
        return entries
    for path in sorted(compiled.glob(_COMPILED_GLOB)):
        policy_id = path.parent.parent.name
        try:
            entry = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue  # a malformed entry must not take the others down
        if isinstance(entry, dict) and entry.get("type") == "command":
            entries[policy_id] = entry
    return entries


def install_agent_hooks(repo_root: Path) -> list[str]:
    """Rewrite `.github/hooks/chock.json` from compiled entries. Returns policy ids installed."""
    repo_root = Path(repo_root)
    entries = _compiled_entries(repo_root)
    dest = repo_root / HOOKS_REL
    if not entries:
        # Nothing to enforce here: remove a stale file rather than leave an empty hook set.
        if dest.exists():
            dest.unlink()
        return []
    vendor_runtime(repo_root, "vscode_copilot")
    doc = {"version": 1, "hooks": {"preToolUse": [entries[pid] for pid in sorted(entries)]}}
    dest.parent.mkdir(parents=True, exist_ok=True)
    write_generated_json(dest, doc)
    return sorted(entries)


def _installed_entries(repo_root: Path) -> list[dict]:
    dest = Path(repo_root) / HOOKS_REL
    if not dest.exists():
        return []
    try:
        doc = json.loads(dest.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    hooks = doc.get("hooks") if isinstance(doc, dict) else None
    pre = hooks.get("preToolUse") if isinstance(hooks, dict) else None
    return [e for e in pre if isinstance(e, dict)] if isinstance(pre, list) else []


def installed_agent_hooks_policy_ids(repo_root: Path) -> set[str]:
    """Policy ids whose compiled entry is byte-present in the installed `.github/hooks/chock.json`."""
    repo_root = Path(repo_root)
    installed = _installed_entries(repo_root)
    if not installed:
        return set()
    return {pid for pid, entry in _compiled_entries(repo_root).items() if entry in installed}
