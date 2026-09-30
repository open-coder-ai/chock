"""A plugin ships the sibling Python packages its guard imports, next to the guard."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Callable

import pytest
import yaml
from conftest import run_hook_command

from chock.plugin.claude import build_claude_plugin, claude_plugin_differences, stale_claude_files
from chock.plugin.codex import build_codex_plugin
from chock.plugin.copilot import build_copilot_plugin
from chock.plugin.cursor import build_cursor_plugin
from chock.plugin.devin import build_devin_plugin

POLICY_ID = "block-tmp-danger"
PKG = "tinyparse"
GUARD = f"""import sys

from {PKG} import is_destructive
from {PKG}.deep import REASON

if is_destructive(sys.argv[1:]):
    print(REASON)
    sys.exit(1)
"""
BUILDERS: dict[str, Callable[..., list[Path]]] = {
    "claude": build_claude_plugin,
    "codex": build_codex_plugin,
    "copilot": build_copilot_plugin,
    "cursor": build_cursor_plugin,
    "devin": build_devin_plugin,
}


def _policy(tmp_path: Path) -> tuple[Path, dict]:
    pack = tmp_path / ".agents" / "policies" / POLICY_ID
    impl = pack / "implementations"
    (impl / PKG / "deep").mkdir(parents=True)
    manifest = {
        "id": POLICY_ID,
        "name": "Block Tmp Danger",
        "version": "0.0.1",
        "description": "Block rm -rf.",
        "artifact": "hook",
        "enforcement": "block",
    }
    (pack / "manifest.yaml").write_text(yaml.safe_dump(manifest), encoding="utf-8")
    (impl / f"{POLICY_ID}.py").write_text(GUARD, encoding="utf-8")
    (impl / PKG / "__init__.py").write_text(
        "def is_destructive(argv):\n    return argv[:1] == ['rm'] and '-rf' in argv\n", encoding="utf-8"
    )
    (impl / PKG / "deep" / "__init__.py").write_text("REASON = 'no rm -rf'\n", encoding="utf-8")
    return pack, manifest


@pytest.mark.parametrize("vendor", sorted(BUILDERS))
def test_every_vendor_ships_the_guards_sibling_package(tmp_path: Path, vendor: str) -> None:
    pack, manifest = _policy(tmp_path)
    out = tmp_path / "dist"
    BUILDERS[vendor](pack, manifest, tmp_path, out)
    scripts = next(out.rglob(f"{POLICY_ID}.py")).parent
    assert (scripts / PKG / "__init__.py").is_file()
    assert (scripts / PKG / "deep" / "__init__.py").read_text(encoding="utf-8") == "REASON = 'no rm -rf'\n"


def test_only_importable_packages_are_shipped_without_caches(tmp_path: Path) -> None:
    pack, manifest = _policy(tmp_path)
    impl = pack / "implementations"
    (impl / "notpkg").mkdir()
    (impl / "notpkg" / "helper.py").write_text("X = 1\n", encoding="utf-8")
    (impl / PKG / "__pycache__").mkdir()
    (impl / PKG / "__pycache__" / "x.cpython-311.pyc").write_bytes(b"\0\1")
    (impl / PKG / "__pycache__" / "stray.py").write_text("X = 1\n", encoding="utf-8")
    (impl / PKG / "data.pyc").write_bytes(b"\0\1")
    out = tmp_path / "dist"
    build_claude_plugin(pack, manifest, tmp_path, out)
    shipped = {p.relative_to(out / "scripts").as_posix() for p in (out / "scripts").rglob("*") if p.is_file()}
    assert {f"{PKG}/__init__.py", f"{PKG}/deep/__init__.py", f"{POLICY_ID}.py"} <= shipped
    assert not [name for name in shipped if name.startswith("notpkg") or "__pycache__" in name or name.endswith(".pyc")]


def test_stale_and_differences_cover_the_package(tmp_path: Path) -> None:
    pack, manifest = _policy(tmp_path)
    out = tmp_path / "dist"
    build_claude_plugin(pack, manifest, tmp_path, out)
    assert claude_plugin_differences(pack, manifest, tmp_path, out) == []
    assert stale_claude_files(pack, manifest, tmp_path, out) == []
    (out / "scripts" / PKG / "__init__.py").unlink()
    assert claude_plugin_differences(pack, manifest, tmp_path, out)
    build_claude_plugin(pack, manifest, tmp_path, out)
    (pack / "implementations" / PKG / "deep" / "__init__.py").unlink()
    (pack / "implementations" / PKG / "deep").rmdir()
    assert stale_claude_files(pack, manifest, tmp_path, out) == [out / "scripts" / PKG / "deep" / "__init__.py"]


def test_built_claude_guard_denies_through_its_launcher(tmp_path: Path) -> None:
    pack, manifest = _policy(tmp_path)
    out = tmp_path / "plugin"
    build_claude_plugin(pack, manifest, tmp_path, out)
    hooks = json.loads((out / "hooks" / "hooks.json").read_text(encoding="utf-8"))
    command = hooks["hooks"]["PreToolUse"][0]["hooks"][0]["command"].replace("${CLAUDE_PLUGIN_ROOT}", out.as_posix())
    outside = tmp_path / "not-a-repo"
    outside.mkdir()
    payload = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": "rm -rf /"}}
    proc = run_hook_command(command, outside, json.dumps(payload))
    assert proc.returncode == 0, proc.stderr
    decision = json.loads(proc.stdout)["hookSpecificOutput"]
    assert decision["permissionDecision"] == "deny", (decision, sys.version)
    assert "crash" not in proc.stderr
