"""Cursor pre-tool-use surface: same protocol as Claude, different envelope.

Pins four claims: guard discovery is by convention (`implementations/<id>.sh`), the
Cursor fragment and the Claude fragment carry the same command, the installer follows
the committed-file discipline, and the coverage claim is per-agent -- wiring Claude
must never raise `enforced` on Cursor rows, nor the reverse.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from conftest import baseline_policy

from chock.compile.compiler import compile_policy
from chock.compile.surfaces import Surface
from chock.hooks.cursor_install import install_cursor_hooks, installed_cursor_policy_ids
from chock.hooks.pretooluse_install import INTERPRETER_PLACEHOLDER, install_pretooluse_hooks

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
    # The hardcoded-map era silently unwired every guard not named in it. Any policy with
    # implementations/<id>.sh must emit both fragments.
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


def test_both_fragments_carry_the_same_command(tmp_path: Path) -> None:
    policy = baseline_policy("block-destructive-commands")
    out = tmp_path / ".chock" / "compiled"
    compile_policy(policy, targets=[Surface.PRE_TOOL_USE.value], output_root=out, agents=["claude", "cursor"])
    surface_dir = out / "block-destructive-commands" / "pre-tool-use"
    claude = json.loads((surface_dir / "pretooluse.json").read_text())["hooks"][0]["command"]
    cursor = json.loads((surface_dir / "cursor-hooks.json").read_text())["beforeShellExecution"][0]["command"]
    assert claude == cursor, "one emit, one command: the two envelopes must never disagree"
    assert INTERPRETER_PLACEHOLDER in cursor


def test_install_bakes_and_preserves_foreign_entries() -> None:
    repo = _fresh_repo()
    hooks_path = repo / ".cursor" / "hooks.json"
    hooks_path.parent.mkdir(parents=True, exist_ok=True)
    theirs = {"command": "./scripts/audit.sh"}
    hooks_path.write_text(json.dumps({"version": 1, "hooks": {"beforeShellExecution": [theirs]}}), encoding="utf-8")
    install_cursor_hooks(repo)
    settings = json.loads(hooks_path.read_text(encoding="utf-8"))
    entries = settings["hooks"]["beforeShellExecution"]
    assert entries[0] == theirs, "the adopter's own entry must survive, first"
    assert len(entries) == 2
    assert INTERPRETER_PLACEHOLDER not in entries[1]["command"]
    assert sys.executable in entries[1]["command"]


def test_reinstall_does_not_churn_a_committed_entry() -> None:
    repo = _fresh_repo()
    install_cursor_hooks(repo)
    hooks_path = repo / ".cursor" / "hooks.json"
    settings = json.loads(hooks_path.read_text(encoding="utf-8"))
    entry = settings["hooks"]["beforeShellExecution"][0]
    entry["command"] = '"/usr/bin/python3.12"' + entry["command"][entry["command"].index(' "') :]
    hooks_path.write_text(json.dumps(settings, indent=2), encoding="utf-8")
    before = hooks_path.read_text(encoding="utf-8")
    install_cursor_hooks(repo)
    assert json.loads(hooks_path.read_text(encoding="utf-8")) == json.loads(before)
    assert "block-destructive-commands" in installed_cursor_policy_ids(repo)


def test_coverage_witness_is_per_agent() -> None:
    # Wiring Claude must not raise `enforced` on Cursor rows, nor the reverse.
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
        return json.loads((repo / ".chock" / "coverage.json").read_text())["block-destructive-commands"]

    baseline = recompile_and_read()
    assert baseline["claude"] != "enforced" and baseline["cursor"] != "enforced"

    install_pretooluse_hooks(repo)
    after_claude = recompile_and_read()
    assert after_claude["claude"] == "enforced"
    assert after_claude["cursor"] != "enforced", "Claude's install is not evidence for Cursor"

    install_cursor_hooks(repo)
    after_both = recompile_and_read()
    assert after_both["cursor"] == "enforced"


def test_adapter_parses_cursor_payload_and_denies() -> None:
    # Cursor's beforeShellExecution payload carries `command` at the top level; the
    # vendored adapter must deny (exit 2) through the same guard.
    repo = _fresh_repo()
    install_cursor_hooks(repo)
    settings = json.loads((repo / ".cursor" / "hooks.json").read_text(encoding="utf-8"))
    command = settings["hooks"]["beforeShellExecution"][0]["command"].replace("${CLAUDE_PROJECT_DIR}", str(repo))
    payload = json.dumps({"command": "rm -rf /", "cwd": str(repo), "hook_event_name": "beforeShellExecution"})
    proc = subprocess.run(
        command,
        cwd=repo,
        shell=True,
        env={**os.environ, "CLAUDE_PROJECT_DIR": str(repo)},
        capture_output=True,
        text=True,
        input=payload,
    )
    assert proc.returncode == 2, f"adapter did not deny a Cursor-shaped payload:\n{proc.stdout}{proc.stderr}"
