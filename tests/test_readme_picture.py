"""The README's 'How it works' figure is tied to its data file, the witness ledger and the docs copy."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "docs" / "assets" / "readme"
FIGURE = json.loads((ASSETS / "where-chock-sits.json").read_text(encoding="utf-8"))
PNG = "docs/assets/readme/v2/where-chock-sits.png"


def test_figure_sits_directly_under_how_it_works_with_the_data_alt() -> None:
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    after = text.split("## How it works\n\n", 1)[1]
    first = after.split("\n", 1)[0]
    assert first.startswith("<p><img ") and PNG in first
    assert f'alt="{FIGURE["alt"]}"' in first


def test_figure_names_only_witnessed_agents() -> None:
    witnesses = json.loads((ROOT / "src/chock/data/witnesses.json").read_text(encoding="utf-8"))
    clients = " ".join(w["client"] for w in witnesses).lower().replace(" ", "")
    for name in FIGURE["agent"]["names"]:
        assert name.lower().replace(" ", "") in clients, name


def test_figure_labels_the_tool_point_as_client_dependent_and_the_others_as_every_agent() -> None:
    scopes = [p["scope"] for p in FIGURE["chock"]["points"]]
    assert scopes == ["where the agent has hooks", "every agent", "every agent"]
    assert {s["tier"] for s in FIGURE["stops"]} <= {"commit", "in-agent"}
    assert len(FIGURE["stops"]) == 5


def test_figure_png_exists_and_architecture_doc_shows_it_above_the_old_figure() -> None:
    assert (ROOT / PNG).stat().st_size > 10_000
    doc = (ROOT / "docs" / "architecture.md").read_text(encoding="utf-8")
    new, old = doc.index("assets/readme/v2/where-chock-sits.png"), doc.index("assets/architecture.svg")
    assert new < old
    assert f'alt="{FIGURE["alt"]}"' in doc


def test_renderer_registers_the_figure() -> None:
    assert "'v2/where-chock-sits': WHERE" in (ASSETS / "render.mjs").read_text(encoding="utf-8")
