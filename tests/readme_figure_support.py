"""Shared by the README figure tests: the figure data, the engine-derived set of acting points and the node layout checks."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "docs" / "assets" / "readme"
FIGURE = json.loads((ASSETS / "where-chock-sits.json").read_text(encoding="utf-8"))
OTHER_POINTS = {"ambient-rule", "mcp-gateway", "git-commit", "git-push", "ci-gate"}
GIT_POINTS = {"commit": "git-commit", "commit-msg": "git-commit", "push": "git-push"}


def engine_acts() -> set[str]:
    """Every point the engine acts on: the agentseam events used in src/chock, the surfaces and the git events."""
    from agentseam import contract

    from chock.compile.emitters import SCRIPT_EVENTS
    from chock.compile.surface_kinds import Surface

    wanted = {event.upper(): event for event in contract.EVENTS}
    used = {
        wanted[name]
        for path in (ROOT / "src" / "chock").rglob("*.py")
        for name in re.findall(r"_contract\.([A-Z_]+)", path.read_text(encoding="utf-8"))
        if name in wanted
    }
    surfaces = {s.value for s in Surface} & {"ambient-rule", "mcp-gateway", "ci-gate"}
    return used | surfaces | {GIT_POINTS[event] for event in SCRIPT_EVENTS}


def crowded(module: str) -> list:
    """The shape pairs the figure module's own layout reports as too close; skips when node is missing."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    script = (
        f"import {{layout, crowded}} from './docs/assets/readme/{module}.mjs';"
        "import {readFileSync} from 'node:fs';"
        "const W = JSON.parse(readFileSync('docs/assets/readme/where-chock-sits.json', 'utf8'));"
        "console.log(JSON.stringify(crowded(layout(W))));"
    )
    done = subprocess.run(
        [node, "--input-type=module", "-e", script], cwd=ROOT, capture_output=True, text=True, check=False
    )
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)
