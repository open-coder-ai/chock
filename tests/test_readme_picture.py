"""The README's 'How it works' figure is tied to its data file, the proving tests and the docs copy."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "docs" / "assets" / "readme"
FIGURE = json.loads((ASSETS / "where-chock-sits.json").read_text(encoding="utf-8"))
PNG = "docs/assets/readme/v2/where-chock-sits.png"
SCOPES = ["", "where the agent has hooks", "every agent, and people", "every agent"]


def test_figure_sits_directly_under_how_it_works_with_the_data_alt() -> None:
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    first = text.split("## How it works\n\n", 1)[1].split("\n", 1)[0]
    assert first.startswith("<p><img ") and PNG in first
    assert f'alt="{FIGURE["alt"]}"' in first


def test_four_connectors_with_their_scopes_each_tied_to_a_proving_test() -> None:
    connectors = FIGURE["connectors"]
    assert [c["n"] for c in connectors] == ["1", "2", "3", "4"]
    assert [c["scope"] for c in connectors] == SCOPES
    for connector in connectors:
        assert connector["proof"], connector["name"]
        for rel in connector["proof"]:
            assert (ROOT / rel).is_file(), rel


def test_connector_proofs_name_what_they_prove() -> None:
    proofs = {c["n"]: c["proof"] for c in FIGURE["connectors"]}
    assert "chock:pointer:start" in (ROOT / "src/chock/scaffold/data/pointer_block.md").read_text(encoding="utf-8")
    assert "permissionDecision" in (ROOT / proofs["2"][1]).read_text(encoding="utf-8")
    assert "--event ci" in (ROOT / proofs["4"][0]).read_text(encoding="utf-8")


def test_components_are_generic_and_the_stops_are_five() -> None:
    shown = {k: v for k, v in FIGURE.items() if k != "_"}
    shown["connectors"] = [{k: v for k, v in c.items() if k != "proof"} for c in FIGURE["connectors"]]
    text = json.dumps(shown).lower()
    for vendor in ("claude", "cursor", "copilot", "codex", "gemini", "devin"):
        assert vendor not in text, vendor
    assert len(FIGURE["stops"]) == 5
    assert {s["tier"] for s in FIGURE["stops"]} <= {"commit", "in-agent"}
    assert "floating image tag such as latest" in text


def test_figure_png_exists_and_architecture_doc_shows_it_above_the_old_figure() -> None:
    assert (ROOT / PNG).stat().st_size > 10_000
    doc = (ROOT / "docs" / "architecture.md").read_text(encoding="utf-8")
    assert doc.index("assets/readme/v2/where-chock-sits.png") < doc.index("assets/architecture.svg")
    assert f'alt="{FIGURE["alt"]}"' in doc


def test_renderer_registers_the_figure() -> None:
    assert "'v2/where-chock-sits': WHERE" in (ASSETS / "render.mjs").read_text(encoding="utf-8")
