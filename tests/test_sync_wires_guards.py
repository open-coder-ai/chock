"""The documented adopter flow (init + add + sync) must fully wire the guards.

PreToolUse installation used to live only behind the `install-hooks` alias, so the flow
every doc teaches left compiled fragments uninstalled: coverage honestly said `advisory`
while the docs said sync "rewires the repo". These tests pin that one plain `chock sync`
ends with the guard installed on every wired agent and coverage claiming it.
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
        # Explicit --agents: coverage.json only enumerates the repo's configured
        # supported_agents, and the default trio (claude/copilot/gemini) omits cursor --
        # this fixture's own assertions need both claude and cursor selected.
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


def test_one_sync_wires_and_claims_every_guard_surface() -> None:
    repo = _fresh_repo()
    proc = _sync(repo)
    assert proc.returncode == 0, proc.stdout + proc.stderr

    settings = json.loads((repo / ".claude" / "settings.json").read_text(encoding="utf-8"))
    commands = [h["command"] for e in settings["hooks"]["PreToolUse"] for h in e["hooks"]]
    assert any("block-destructive" in c for c in commands), "sync must install the PreToolUse fragment"

    cursor = json.loads((repo / ".cursor" / "hooks.json").read_text(encoding="utf-8"))
    assert any("block-destructive" in e["command"] for e in cursor["hooks"]["beforeShellExecution"]), (
        "sync must install the Cursor hook entry"
    )

    coverage = json.loads((repo / ".chock" / "coverage.json").read_text(encoding="utf-8"))
    row = coverage["block-destructive-commands"]
    # claude_code's PreToolUse is FAIL_OPEN (agentseam.matrix_data), so installed it reads
    # `best-effort`, never a flat `enforced` (owner decision #9).
    assert row["claude"] == "best-effort", f"coverage must reflect the wiring sync just did: {row}"
    assert row["cursor"] == "enforceable", row


def test_second_sync_is_stable() -> None:
    # The re-derivation must fire only when wiring changes: a second sync leaves
    # settings, hooks config and coverage byte-identical.
    repo = _fresh_repo()
    _sync(repo)
    paths = [
        repo / ".claude" / "settings.json",
        repo / ".cursor" / "hooks.json",
        repo / ".chock" / "coverage.json",
    ]
    before = [p.read_bytes() for p in paths]
    proc = _sync(repo)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert [p.read_bytes() for p in paths] == before, "a no-change sync must not churn committed files"
