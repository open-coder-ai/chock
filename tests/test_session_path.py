"""The session-path figure in docs/architecture.md: the same points in session order, with the same engine checks."""

from __future__ import annotations

from readme_figure_support import FIGURE, crowded, engine_acts

PATH = FIGURE["path"]


def test_diamonds_and_chips_cover_every_point_once() -> None:
    points = FIGURE["points"]
    assert all(len(p["place"]) >= 1 for p in points)
    diamonds = {p["id"] for p in points if p["place"].get("row") or p["place"].get("tag")}
    chips = {p["id"] for p in points if p["place"].get("chip")}
    assert not diamonds & chips and len(diamonds | chips) == len(points)


def test_filled_diamonds_are_the_engine_set_and_notes_are_at_most_four_words() -> None:
    assert {p["id"] for p in FIGURE["points"] if p["acts"]} == engine_acts()
    assert all(len(p["does"].split()) <= 4 for p in FIGURE["points"] if p["acts"] and "does" in p)


def test_the_loop_runs_from_after_post_tool_to_the_model_step() -> None:
    loop = PATH["paths"]["agent"]["loop"]
    assert loop["after"] == "post_tool" and PATH["paths"]["agent"]["steps"][loop["to"]]["text"].startswith("The model")


def test_no_two_shapes_of_the_path_layout_are_too_close() -> None:
    assert crowded("session-path") == []
