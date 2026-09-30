"""Cursor pre-tool-use surface: same protocol as Claude, different envelope."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest
from conftest import baseline_policy, run_hook_command

from chock.compile.compiler import compile_policy
from chock.compile.surfaces import Surface
from chock.hooks.in_agent_install import install_hooks, installed_policy_ids
from chock.hooks.launch import hook_command

FRAMEWORK_ROOT = Path(__file__).resolve().parents[1]


def _fresh_repo(policy: str = "block-destructive-commands") -> Path:
    repo = Path(tempfile.mkdtemp()) / "r"
    repo.mkdir()
    env = {**os.environ, "PYTHONPATH": str(FRAMEWORK_ROOT / "src")}
    subprocess.run(["git", "init", "-q", "."], cwd=repo, check=True)
    subprocess.run(
        [sys.executable, "-m", "chock.cli", "init", ".", "--skip-hooks"], cwd=repo, capture_output=True, env=env
    )
    shutil.copytree(baseline_policy(policy), repo / ".agents" / "policies" / policy)
    subprocess.run(
        [sys.executable, "-m", "chock.cli", "recompile", "--skip-hooks", "--repo", str(repo)],
        cwd=repo,
        capture_output=True,
        env=env,
    )
    return repo


def test_convention_named_guards_emit_fragments(tmp_path: Path) -> None:
    policy = tmp_path / "policies" / "block-anything"
    (policy / "implementations").mkdir(parents=True)
    (policy / "implementations" / "block-anything.sh").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    (policy / "manifest.yaml").write_text(
        "id: block-anything\nartifact: rule\nenforcement: advise\nrule:\n  text: x\n", encoding="utf-8"
    )
    out = tmp_path / "compiled"
    compile_policy(policy, targets=[Surface.PRE_TOOL_USE.value], output_root=out, agents=["claude", "cursor"])
    surface_dir = out / "block-anything" / "pre-tool-use"
    assert (surface_dir / "pretooluse.json").exists()
    assert (surface_dir / "cursor-hooks.json").exists()


def test_both_fragments_reference_the_same_guard(tmp_path: Path) -> None:
    """One emit, one guard: the two envelopes must never disagree about WHAT runs."""
    policy = baseline_policy("block-destructive-commands")
    out = tmp_path / ".chock" / "compiled"
    compile_policy(policy, targets=[Surface.PRE_TOOL_USE.value], output_root=out, agents=["claude", "cursor"])
    surface_dir = out / "block-destructive-commands" / "pre-tool-use"
    claude = json.loads((surface_dir / "pretooluse.json").read_text())["hooks"][0]["command"]
    cursor = json.loads((surface_dir / "cursor-hooks.json").read_text())["beforeShellExecution"][0]["command"]
    guard = ".agents/policies/block-destructive-commands/implementations/block-destructive-commands.py"
    assert claude == hook_command(".chock/bin/claude_code.py", "--guard", guard)
    assert cursor == hook_command(".chock/bin/cursor.py", "--guard", guard)
    assert claude.split("--guard", 1)[1] == cursor.split("--guard", 1)[1], "same guard, both envelopes"


def _hooks_path(repo: Path) -> Path:
    return repo / ".cursor" / "hooks.json"


def test_install_writes_the_compiled_entry_and_preserves_foreign_entries() -> None:
    repo = _fresh_repo()
    hooks_path = _hooks_path(repo)
    hooks_path.parent.mkdir(parents=True, exist_ok=True)
    theirs = {"command": "./scripts/audit.sh"}
    hooks_path.write_text(json.dumps({"version": 1, "hooks": {"beforeShellExecution": [theirs]}}), encoding="utf-8")
    install_hooks(repo, "cursor")
    entries = json.loads(hooks_path.read_text(encoding="utf-8"))["hooks"]["beforeShellExecution"]
    assert entries[0] == theirs, "the adopter's own entry must survive, first"
    assert len(entries) == 2
    compiled = repo / ".chock" / "compiled" / "block-destructive-commands" / "pre-tool-use" / "cursor-hooks.json"
    assert entries[1] == json.loads(compiled.read_text(encoding="utf-8"))["beforeShellExecution"][0]
    assert sys.executable not in entries[1]["command"]


def test_reinstall_on_another_machine_is_byte_identical(monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _fresh_repo()
    install_hooks(repo, "cursor")
    before = _hooks_path(repo).read_bytes()
    monkeypatch.setattr(sys, "executable", "/opt/elsewhere/bin/python3")
    install_hooks(repo, "cursor")
    assert _hooks_path(repo).read_bytes() == before
    assert "block-destructive-commands" in installed_policy_ids(repo, "cursor")


def test_an_old_baked_entry_is_replaced_by_the_launcher_form() -> None:
    repo = _fresh_repo()
    install_hooks(repo, "cursor")
    hooks_path = _hooks_path(repo)
    settings = json.loads(hooks_path.read_text(encoding="utf-8"))
    current = settings["hooks"]["beforeShellExecution"][0]
    root = "${CLAUDE_PROJECT_DIR}"
    guard = ".agents/policies/block-destructive-commands/implementations/block-destructive-commands.py"
    settings["hooks"]["beforeShellExecution"] = [
        {"command": f'"/usr/bin/python3" "{root}/.chock/bin/cursor.py" --guard "{root}/{guard}"', "timeout": 30}
    ]
    hooks_path.write_text(json.dumps(settings, indent=2), encoding="utf-8")
    install_hooks(repo, "cursor")
    entries = json.loads(hooks_path.read_text(encoding="utf-8"))["hooks"]["beforeShellExecution"]
    assert entries == [current], "the old entry is ours: replaced by the launcher form, not duplicated"


def test_coverage_witness_is_per_agent() -> None:
    repo = _fresh_repo()
    env = {**os.environ, "PYTHONPATH": str(FRAMEWORK_ROOT / "src")}

    def recompile_and_read() -> dict:
        subprocess.run(
            [
                sys.executable,
                "-m",
                "chock.cli",
                "recompile",
                "--skip-hooks",
                "--repo",
                str(repo),
                "--agents",
                "claude,cursor",
            ],
            cwd=repo,
            capture_output=True,
            env=env,
        )
        row = json.loads((repo / ".chock" / "coverage.json").read_text())["block-destructive-commands"]
        return {agent: cell["level"] for agent, cell in row.items()}

    baseline = recompile_and_read()
    assert baseline["claude"] != "enforced" and baseline["cursor"] != "enforced"

    install_hooks(repo, "claude_code")
    after_claude = recompile_and_read()
    assert after_claude["claude"] == "best-effort"
    assert after_claude["cursor"] != "enforced", "Claude's install is not evidence for Cursor"

    install_hooks(repo, "cursor")
    after_both = recompile_and_read()
    assert after_both["cursor"] == "enforceable"


def test_adapter_parses_cursor_payload_and_denies() -> None:
    repo = _fresh_repo()
    install_hooks(repo, "cursor")
    settings = json.loads((repo / ".cursor" / "hooks.json").read_text(encoding="utf-8"))
    command = settings["hooks"]["beforeShellExecution"][0]["command"]
    payload = json.dumps({"command": "rm -rf /", "cwd": str(repo), "hook_event_name": "beforeShellExecution"})
    nested = repo / "sub" / "dir"
    nested.mkdir(parents=True)
    for cwd in (repo, nested):
        proc = run_hook_command(command, cwd, payload)
        assert proc.returncode == 0, f"adapter errored on a Cursor-shaped payload:\n{proc.stdout}{proc.stderr}"
        decision = json.loads(proc.stdout)
        assert decision["permission"] == "deny", (
            f"adapter did not deny a Cursor-shaped payload from {cwd}:\n{proc.stdout}{proc.stderr}"
        )
