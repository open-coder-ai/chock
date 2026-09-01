"""Cursor pre-tool-use surface: same protocol as Claude, different envelope."""

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
    assert INTERPRETER_PLACEHOLDER in claude
    assert INTERPRETER_PLACEHOLDER in cursor
    assert '--guard "${CLAUDE_PROJECT_DIR}/.agents/policies/block-destructive-commands' in claude
    assert claude.split("--guard", 1)[1] == cursor.split("--guard", 1)[1], "same guard, both envelopes"
    assert '"${CLAUDE_PROJECT_DIR}/.chock/bin/claude_code.py"' in claude
    assert '"${CLAUDE_PROJECT_DIR}/.chock/bin/cursor.py"' in cursor


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


def _fake_but_real_interpreter(tmp_path: Path) -> str:
    """A path that is not `sys.executable` but genuinely resolves on this machine."""
    import shutil

    fake = tmp_path / "another-machine-python3"
    shutil.copy(sys.executable, fake)
    fake.chmod(0o755)
    return str(fake)


def test_reinstall_does_not_churn_a_committed_entry(tmp_path: Path) -> None:
    repo = _fresh_repo()
    install_cursor_hooks(repo)
    hooks_path = repo / ".cursor" / "hooks.json"
    settings = json.loads(hooks_path.read_text(encoding="utf-8"))
    entry = settings["hooks"]["beforeShellExecution"][0]
    other = _fake_but_real_interpreter(tmp_path)
    entry["command"] = f'"{other}"' + entry["command"][entry["command"].index(' "') :]
    hooks_path.write_text(json.dumps(settings, indent=2), encoding="utf-8")
    before = hooks_path.read_text(encoding="utf-8")
    install_cursor_hooks(repo)
    assert json.loads(hooks_path.read_text(encoding="utf-8")) == json.loads(before)
    assert "block-destructive-commands" in installed_cursor_policy_ids(repo)


def test_reinstall_rebakes_an_interpreter_that_no_longer_resolves() -> None:
    repo = _fresh_repo()
    install_cursor_hooks(repo)
    hooks_path = repo / ".cursor" / "hooks.json"
    settings = json.loads(hooks_path.read_text(encoding="utf-8"))
    entry = settings["hooks"]["beforeShellExecution"][0]
    entry["command"] = (
        '"/usr/local/bin/definitely-not-a-real-interpreter3"' + entry["command"][entry["command"].index(' "') :]
    )
    hooks_path.write_text(json.dumps(settings, indent=2), encoding="utf-8")
    install_cursor_hooks(repo)
    settings = json.loads(hooks_path.read_text(encoding="utf-8"))
    command = settings["hooks"]["beforeShellExecution"][0]["command"]
    assert sys.executable in command, "a dead interpreter path must be rebaked to one that runs here"


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

    install_pretooluse_hooks(repo)
    after_claude = recompile_and_read()
    assert after_claude["claude"] == "best-effort"
    assert after_claude["cursor"] != "enforced", "Claude's install is not evidence for Cursor"

    install_cursor_hooks(repo)
    after_both = recompile_and_read()
    assert after_both["cursor"] == "enforceable"


def test_adapter_parses_cursor_payload_and_denies() -> None:
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
    assert proc.returncode == 0, f"adapter errored on a Cursor-shaped payload:\n{proc.stdout}{proc.stderr}"
    decision = json.loads(proc.stdout)
    assert decision["permission"] == "deny", (
        f"adapter did not deny a Cursor-shaped payload:\n{proc.stdout}{proc.stderr}"
    )
