"""Fixture policies for plugin packaging: a guard alone, a gate alone, and both on one policy."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Callable

import yaml

from chock.plugin import claude, codex, copilot, cursor, devin

POLICY_ID = "protect-config"
PROTECTED = ".mcp.json"
#: Refuses any shell command naming the protected file, the way a real guard reads its argv.
GUARD = (
    "import sys\n"
    f"if any({PROTECTED!r} in arg for arg in sys.argv[1:]):\n"
    f"    print('protect-config: shell write to {PROTECTED}')\n"
    "    sys.exit(1)\n"
)
#: The catalog protect-agent-config shape: a path-only gate, its content pattern never matching.
GATE = {
    "kind": "content_regex",
    "on": ["tool_use"],
    "action": "block",
    "message": "agent config is regenerated, not hand-edited",
    "params": {"scan": "added_lines", "forbidden_path_regex": r"\.mcp\.json", "content_pattern": "(?!)"},
}

#: format -> (agent, files function, hooks path inside the package)
STORES: dict[str, tuple[str, Callable[..., dict[Path, str]], str]] = {
    "claude": ("claude_code", claude.claude_plugin_files, "hooks/hooks.json"),
    "codex": ("codex_cli", codex.codex_plugin_files, codex.HOOKS_REL),
    "copilot": ("vscode_copilot", copilot.copilot_plugin_files, copilot.HOOKS_REL),
    "cursor": ("cursor", cursor.cursor_plugin_files, cursor.HOOKS_REL),
    "devin": ("devin", devin.devin_plugin_files, devin.HOOKS_REL),
}
BUILDERS = {
    "claude": claude.build_claude_plugin,
    "codex": codex.build_codex_plugin,
    "copilot": copilot.build_copilot_plugin,
    "cursor": cursor.build_cursor_plugin,
    "devin": devin.build_devin_plugin,
}
DIFFERS = {
    "claude": claude.claude_plugin_differences,
    "codex": codex.codex_plugin_differences,
    "copilot": copilot.copilot_plugin_differences,
    "cursor": cursor.cursor_plugin_differences,
    "devin": devin.devin_plugin_differences,
}
#: Engine files copied verbatim into every enforcing package; they change with the engine, not
#: with how a package is assembled, so the single-half golden leaves them out.
RUNTIME_NAMES = frozenset({"claude_code.py", "codex_cli.py", "vscode_copilot.py", "cursor.py", "devin.py"})
RUNTIME_NAMES |= {"launch.sh", "gate.py"}


def manifest(*, guard: bool, gate: bool, policy_id: str = POLICY_ID) -> dict[str, Any]:
    """A policy manifest carrying the guard, the gate, or both."""
    data: dict[str, Any] = {
        "id": policy_id,
        "name": "Protect Config",
        "version": "0.0.1",
        "description": "Refuse edits to agent config.",
        "artifact": "hook",
        "enforcement": "block",
        "provenance": {"author": "t", "license": "Apache-2.0"},
        "lifecycle": {"status": "draft"},
    }
    if gate:
        data["hook"] = {"gate": GATE}
    return data


def make_policy(root: Path, *, guard: bool, gate: bool, policy_id: str = POLICY_ID) -> tuple[Path, dict[str, Any]]:
    """Write the policy under `root/.agents/policies/<id>/` and return (its dir, its manifest)."""
    data = manifest(guard=guard, gate=gate, policy_id=policy_id)
    pack = root / ".agents" / "policies" / policy_id
    (pack / "implementations").mkdir(parents=True, exist_ok=True)
    (pack / "manifest.yaml").write_text(yaml.safe_dump(data), encoding="utf-8")
    if guard:
        (pack / "implementations" / f"{policy_id}.py").write_text(GUARD, encoding="utf-8")
    return pack, data


def golden_of(files: dict[Path, str]) -> dict[str, str]:
    """{package path: sha256} of what a package assembles, engine runtime copies left out."""
    return {
        rel.as_posix(): hashlib.sha256(text.encode("utf-8")).hexdigest()
        for rel, text in sorted(files.items())
        if rel.name not in RUNTIME_NAMES
    }
