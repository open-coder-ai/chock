"""The README's 'How it works' figure is tied to its data file, the proving tests and the docs copy."""

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
PNG = "docs/assets/readme/v2/where-chock-sits.png"


def test_figure_sits_directly_under_how_it_works_with_the_data_alt() -> None:
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    first = text.split("## How it works\n\n", 1)[1].split("\n", 1)[0]
    assert first.startswith("<p><img ") and PNG in first
    assert f'alt="{FIGURE["alt"]}"' in first


AGENT_POINTS = {"ambient-rule", "mcp-gateway", "git-commit", "git-push", "ci-gate"}
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


def test_agentseam_points_equal_the_contract_events_and_acting_points_equal_the_engine() -> None:
    from agentseam import contract

    points = FIGURE["points"]
    assert {p["id"] for p in points if p["source"] == "agentseam"} == set(contract.EVENTS)
    assert {p["id"] for p in points if p["source"] == "chock"} == AGENT_POINTS
    assert len({p["id"] for p in points}) == len(points)
    assert {p["id"] for p in points if p["acts"]} == engine_acts()
    assert all(len(p["label"].split()) <= 3 for p in points)
    assert all(len(p["does"].split()) <= 4 for p in points if p["acts"] and "does" in p)
    assert all(("does" in p) == (p["acts"] and "chip" not in p["place"]) for p in points)
    assert all(len(p["place"]) >= 1 for p in points)


def test_no_prompt_submit_hook_is_wired_so_none_is_drawn() -> None:
    sources = " ".join(p.read_text(encoding="utf-8") for p in (ROOT / "src" / "chock").rglob("*.py"))
    assert "PROMPT_SUBMIT" not in sources
    assert not [p for p in FIGURE["points"] if p["id"] == "prompt_submit" and p["acts"]]


def test_every_acting_point_has_existing_proving_tests() -> None:
    for point in FIGURE["points"]:
        assert point["scope"], point["id"]
        assert bool(point["proof"]) == point["acts"], point["id"]
        for rel in point["proof"]:
            assert (ROOT / rel).is_file(), rel


def test_components_are_generic_and_the_stops_are_five() -> None:
    shown = {k: v for k, v in FIGURE.items() if k != "_"}
    shown["points"] = [{k: v for k, v in c.items() if k != "proof"} for c in FIGURE["points"]]
    text = json.dumps(shown).lower()
    for vendor in ("claude", "cursor", "copilot", "codex", "gemini", "devin"):
        assert vendor not in text, vendor
    assert "floating-tag containers" in text


def test_figure_png_exists_and_architecture_doc_shows_it_above_the_old_figure() -> None:
    assert (ROOT / PNG).stat().st_size > 10_000
    doc = (ROOT / "docs" / "architecture.md").read_text(encoding="utf-8")
    assert doc.index("assets/readme/v2/where-chock-sits.png") < doc.index("assets/architecture.svg")
    assert f'alt="{FIGURE["alt"]}"' in doc


def test_renderer_registers_the_figure() -> None:
    assert "'v2/where-chock-sits': WHERE" in (ASSETS / "render.mjs").read_text(encoding="utf-8")


def test_architecture_doc_lists_every_point_with_its_scope() -> None:
    doc = (ROOT / "docs" / "architecture.md").read_text(encoding="utf-8")
    for point in FIGURE["points"]:
        assert f"**{point['name']}**" in doc and point["line"] in doc, point["id"]
        assert point["scope"][0].upper() + point["scope"][1:] in doc, point["id"]


def test_figure_has_no_legend_and_five_short_chips() -> None:
    assert len(FIGURE["stops"]) == 5
    assert all(len(chip.split()) <= 4 for chip in FIGURE["stops"])


def test_a_sixth_chip_invites_the_reader_to_add_their_own_policy() -> None:
    own = FIGURE["own"]
    assert own["label"] == "+ your own policy" and own["command"] == "chock new policy"
    assert FIGURE["stops_title"] == "What it stops, for example"
    assert own["label"] not in FIGURE["stops"]
    commands = json.loads((ROOT / "src" / "chock" / "data" / "commands.json").read_text(encoding="utf-8"))
    assert "new" in commands["authoring"]
    for rel in own["proof"]:
        assert (ROOT / rel).is_file(), rel


def test_no_two_shapes_of_the_layout_are_closer_than_the_gap() -> None:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    script = (
        "import {layout, crowded} from './docs/assets/readme/where-chock-sits.mjs';"
        "import {readFileSync} from 'node:fs';"
        "const W = JSON.parse(readFileSync('docs/assets/readme/where-chock-sits.json', 'utf8'));"
        "console.log(JSON.stringify(crowded(layout(W))));"
    )
    done = subprocess.run(
        [node, "--input-type=module", "-e", script], cwd=ROOT, capture_output=True, text=True, check=False
    )
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout) == []
