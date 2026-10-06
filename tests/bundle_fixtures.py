"""Two stand-in policies and a bundle of them, built per client: a write gate and a shell guard."""

from __future__ import annotations

import json
import os
import textwrap
from pathlib import Path
from typing import Any

import yaml
from conftest import init_repo, run_hook_command

from chock.plugin.bundle_build import Member, merged_files
from chock.plugin.claude import claude_plugin_files
from chock.plugin.store import build_store_plugin

GATE_ID = "demo-write-gate"
GUARD_ID = "demo-shell-guard"
ADVISORY_ID = "demo-advice"
BUNDLE_ID = "demo-bundle"
MARKER = "FORBIDDEN"
SIBLING = "tinyparse"
GUARD_SCRIPT = textwrap.dedent(
    f"""\
    import sys

    from {SIBLING} import is_destructive

    if is_destructive(sys.argv[1:]):
        print("no rm -rf")
        sys.exit(1)
    """
)
SIBLING_SOURCE = "def is_destructive(argv):\n    return argv[:1] == ['rm'] and '-rf' in argv\n"
ALL_ROOTS = ("CLAUDE_PLUGIN_ROOT", "PLUGIN_ROOT", "CURSOR_PLUGIN_ROOT", "DEVIN_PLUGIN_ROOT")


def _manifest(policy_id: str, hook: dict | None) -> dict[str, Any]:
    manifest: dict[str, Any] = {
        "id": policy_id,
        "name": policy_id,
        "version": "0.0.1",
        "description": f"{policy_id} stands in for a policy.",
        "artifact": "hook" if hook else "rule",
        "enforcement": "block" if hook else "advise",
        "provenance": {"author": "t", "license": "Apache-2.0"},
        "lifecycle": {"status": "draft"},
    }
    if hook:
        manifest["hook"] = hook
    return manifest


def make_members(root: Path, *, with_advisory: bool = False) -> list[Member]:
    """The write gate (refuses MARKER), the shell guard (refuses rm -rf), and optionally an advisory rule."""
    specs: list[tuple[str, dict | None]] = [
        (
            GATE_ID,
            {
                "gate": {
                    "kind": "content_regex",
                    "on": ["tool_use"],
                    "action": "block",
                    "message": "m",
                    "params": {"content_pattern": MARKER},
                }
            },
        ),
        (GUARD_ID, None),
    ]
    if with_advisory:
        specs.append((ADVISORY_ID, None))
    members = []
    for policy_id, hook in specs:
        pack = root / ".agents" / "policies" / policy_id
        (pack / "implementations").mkdir(parents=True)
        manifest = _manifest(policy_id, hook)
        (pack / "manifest.yaml").write_text(yaml.safe_dump(manifest), encoding="utf-8")
        if policy_id == GUARD_ID:
            (pack / "implementations" / f"{GUARD_ID}.py").write_text(GUARD_SCRIPT, encoding="utf-8")
            (pack / "implementations" / SIBLING).mkdir()
            (pack / "implementations" / SIBLING / "__init__.py").write_text(SIBLING_SOURCE, encoding="utf-8")
        members.append(Member(pack, manifest))
    return members


def bundle(members: list[Member]) -> dict[str, Any]:
    return {
        "id": BUNDLE_ID,
        "version": "0.1.0",
        "description": "Two demo policies.",
        "members": [m.id for m in members],
    }


def write(out: Path, files: dict[Path, str]) -> Path:
    for rel, content in files.items():
        dest = out / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content, encoding="utf-8")
    return out


def build_claude_tree(root: Path, members: list[Member], out: Path) -> None:
    """Every member as its own Claude package under `out/<id>`, and the bundle beside them."""
    for member in members:
        build_store_plugin("claude", claude_plugin_files, member.policy_dir, member.manifest, root, out / member.id)
    write(out / BUNDLE_ID, merged_files("claude", bundle(members), members, root))


def hook_commands(doc: Any) -> list[str]:
    if isinstance(doc, dict):
        own = [doc["command"]] if isinstance(doc.get("command"), str) else []
        return own + [c for v in doc.values() for c in hook_commands(v)]
    return [c for v in doc for c in hook_commands(v)] if isinstance(doc, list) else []


def run_command(command: str, plugin_root: Path, cwd: Path, payload: dict) -> Any:
    """Run one hook command the way a client does, every vendor's root variable pointing at the package."""
    env = {**os.environ, **dict.fromkeys(ALL_ROOTS, plugin_root.as_posix())}
    return run_hook_command(command, cwd, json.dumps(payload), env=env)


def denies(proc: Any) -> bool:
    return proc.returncode == 0 and "deny" in proc.stdout.lower()


def project(tmp_path: Path) -> Path:
    repo = tmp_path / "project"
    repo.mkdir()
    return init_repo(repo)
