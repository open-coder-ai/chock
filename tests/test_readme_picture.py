"""The README's 'How it works' harness figure is tied to its data file, the agentseam events, the engine and the docs."""

from __future__ import annotations

import json

from readme_figure_support import FIGURE, OTHER_POINTS, ROOT, crowded, engine_acts

PNG = "docs/assets/readme/v2/where-chock-sits.png"
HARNESS = FIGURE["harness"]
CARDS = {c["id"] for c in HARNESS["cards"] + HARNESS["repo_cards"]}


def test_figure_sits_directly_under_how_it_works_with_the_data_alt() -> None:
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    first = text.split("## How it works\n\n", 1)[1].split("\n", 1)[0]
    assert first.startswith("<p><img ") and PNG in first
    assert f'alt="{HARNESS["alt"]}"' in first


def test_badges_equal_the_agentseam_events_plus_the_other_points() -> None:
    from agentseam import contract

    points = FIGURE["points"]
    assert {p["id"] for p in points if p["source"] == "agentseam"} == set(contract.EVENTS)
    assert {p["id"] for p in points if p["source"] == "chock"} == OTHER_POINTS
    assert len({p["id"] for p in points}) == len(points)


def test_every_badge_sits_on_exactly_one_card_and_the_model_has_none() -> None:
    assert all(p["on"] in CARDS for p in FIGURE["points"])
    assert not [p for p in FIGURE["points"] if p["on"] == "model"]
    mapping = {p["id"]: p["on"] for p in FIGURE["points"]}
    assert mapping["pre_tool"] == mapping["post_tool"] == mapping["tool_failure"] == "gate"
    assert mapping["stop"] == "loop" and mapping["mcp-gateway"] == "external"
    assert {mapping[i] for i in ("git-commit", "git-push", "ci-gate")} == {"commit", "push", "ci"}


def test_filled_badges_equal_what_the_engine_acts_on_and_each_has_a_proving_test() -> None:
    assert {p["id"] for p in FIGURE["points"] if p["acts"]} == engine_acts()
    for point in FIGURE["points"]:
        assert bool(point["proof"]) == point["acts"], point["id"]
        for rel in point["proof"]:
            assert (ROOT / rel).is_file(), rel


def test_card_lines_are_at_most_six_words_and_arrow_labels_two() -> None:
    assert all(len(c["line"].split()) <= 6 for c in HARNESS["cards"] + HARNESS["repo_cards"])
    assert all(len(label.split()) <= 2 for label in HARNESS["arrows"].values())


def test_no_prompt_submit_hook_is_wired_so_none_is_filled() -> None:
    sources = " ".join(p.read_text(encoding="utf-8") for p in (ROOT / "src" / "chock").rglob("*.py"))
    assert "PROMPT_SUBMIT" not in sources
    assert not [p for p in FIGURE["points"] if p["id"] == "prompt_submit" and p["acts"]]


def test_no_two_shapes_of_the_harness_layout_are_too_close() -> None:
    assert crowded("where-chock-sits") == []


def test_components_are_generic_and_the_stops_end_with_a_sixth_chip() -> None:
    text = str({k: v for k, v in FIGURE.items() if k not in ("_", "points")}).lower()
    for vendor in ("claude", "cursor", "copilot", "codex", "gemini", "devin"):
        assert vendor not in text, vendor
    own = FIGURE["own"]
    assert own["label"] == "+ your own policy" and own["command"] == "chock new policy"
    assert FIGURE["stops_title"] == "What it stops, for example"
    assert len(FIGURE["stops"]) == 5 and own["label"] not in FIGURE["stops"]
    assert all(len(chip.split()) <= 4 for chip in FIGURE["stops"])
    commands = json.loads((ROOT / "src" / "chock" / "data" / "commands.json").read_text(encoding="utf-8"))
    assert "new" in commands["authoring"]


def test_architecture_doc_shows_the_harness_then_the_session_path_and_lists_every_point() -> None:
    doc = (ROOT / "docs" / "architecture.md").read_text(encoding="utf-8")
    assert doc.index("assets/readme/v2/where-chock-sits.png") < doc.index("assets/readme/v2/session-path.png")
    assert doc.index("assets/readme/v2/session-path.png") < doc.index("assets/architecture.svg")
    assert f'alt="{HARNESS["alt"]}"' in doc and f'alt="{FIGURE["path"]["alt"]}"' in doc
    for point in FIGURE["points"]:
        assert f"**{point['name']}**" in doc and point["line"] in doc, point["id"]


def test_renderer_registers_both_figures() -> None:
    render = (ROOT / "docs" / "assets" / "readme" / "render.mjs").read_text(encoding="utf-8")
    assert "'v2/where-chock-sits': WHERE" in render and "'v2/session-path': SESSION_PATH" in render
    for name in ("where-chock-sits", "session-path"):
        assert (ROOT / "docs" / "assets" / "readme" / "v2" / f"{name}.png").stat().st_size > 10_000
