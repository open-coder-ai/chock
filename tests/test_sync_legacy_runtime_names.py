"""A committed config from before the .chock/bin/ per-vendor rename must not double-wire (chock#84)."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from conftest import baseline_policy

FRAMEWORK_ROOT = Path(__file__).resolve().parents[1]


def _sync(repo: Path) -> subprocess.CompletedProcess:
    env = {**os.environ, "PYTHONPATH": str(FRAMEWORK_ROOT / "src")}
    return subprocess.run(
        [sys.executable, "-m", "chock.cli", "sync", "--repo", str(repo)],
        cwd=repo,
        capture_output=True,
        text=True,
        env=env,
    )


def _fresh_repo() -> Path:
    repo = Path(tempfile.mkdtemp()) / "r"
    repo.mkdir()
    env = {**os.environ, "PYTHONPATH": str(FRAMEWORK_ROOT / "src")}
    subprocess.run(["git", "init", "-q", "."], cwd=repo, check=True)
    subprocess.run(
        [sys.executable, "-m", "chock.cli", "init", ".", "--skip-hooks", "--agents", "claude", "cursor"],
        cwd=repo,
        capture_output=True,
        env=env,
    )
    shutil.copytree(
        baseline_policy("block-destructive-commands"),
        repo / ".agents" / "policies" / "block-destructive-commands",
    )
    return repo


def _legacy_pretooluse_entry() -> dict:
    """Shaped like a hook a pre-rename chock sync would have installed into `.claude/settings.json`."""
    return {
        "matcher": "Bash",
        "hooks": [
            {
                "type": "command",
                "command": '"/usr/bin/python3" "${CLAUDE_PROJECT_DIR}/.chock/bin/pretooluse.py" --guard "old.sh"',
                "timeout": 30,
            }
        ],
    }


def _legacy_cursor_entry() -> dict:
    return {
        "command": '"/usr/bin/python3" "${CLAUDE_PROJECT_DIR}/.chock/bin/pretooluse.py" --guard "old.sh"',
        "timeout": 30,
    }


def _legacy_sessionstart_entry() -> dict:
    return {
        "hooks": [
            {
                "type": "command",
                "command": '"/usr/bin/python3" "${CLAUDE_PROJECT_DIR}/.chock/bin/sessionstart.py"',
                "timeout": 300,
            }
        ]
    }


def _seed_legacy_entries(repo: Path) -> None:
    settings_path = repo / ".claude" / "settings.json"
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(
        json.dumps(
            {"hooks": {"PreToolUse": [_legacy_pretooluse_entry()], "SessionStart": [_legacy_sessionstart_entry()]}}
        ),
        encoding="utf-8",
    )

    cursor_path = repo / ".cursor" / "hooks.json"
    cursor_path.parent.mkdir(parents=True, exist_ok=True)
    cursor_path.write_text(
        json.dumps({"hooks": {"beforeShellExecution": [_legacy_cursor_entry()]}}),
        encoding="utf-8",
    )


def test_sync_recognises_legacy_runtime_names_as_its_own() -> None:
    repo = _fresh_repo()
    _seed_legacy_entries(repo)

    proc = _sync(repo)
    assert proc.returncode == 0, proc.stdout + proc.stderr

    settings = json.loads((repo / ".claude" / "settings.json").read_text(encoding="utf-8"))
    pre_tool_use = settings["hooks"]["PreToolUse"]
    session_start = settings["hooks"]["SessionStart"]
    assert len(pre_tool_use) == 1, (
        f"legacy pretooluse.py entry must be replaced, not kept beside the new one: {pre_tool_use}"
    )
    assert len(session_start) == 1, (
        f"legacy sessionstart.py entry must be replaced, not kept beside the new one: {session_start}"
    )

    cursor = json.loads((repo / ".cursor" / "hooks.json").read_text(encoding="utf-8"))
    before_shell = cursor["hooks"]["beforeShellExecution"]
    assert len(before_shell) == 1, f"legacy pretooluse.py cursor entry must be replaced, not doubled: {before_shell}"
