"""The README's 'How it works' figure is tied to its data file, the proving tests and the docs copy."""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "docs" / "assets" / "readme"
FIGURE = json.loads((ASSETS / "where-chock-sits.json").read_text(encoding="utf-8"))
PNG = "docs/assets/readme/v2/where-chock-sits.png"
AGENT_EVENTS = {"SESSION_START", "PRE_TOOL", "POST_TOOL", "TOOL_FAILURE", "STOP", "PROMPT_SUBMIT", "SESSION_END"}


def test_figure_sits_directly_under_how_it_works_with_the_data_alt() -> None:
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    first = text.split("## How it works\n\n", 1)[1].split("\n", 1)[0]
    assert first.startswith("<p><img ") and PNG in first
    assert f'alt="{FIGURE["alt"]}"' in first


SURFACE_POINTS = {"agent-hooks": "pre-tool-use"}
NOT_DRAWN = {"managed-setting", "gateway", "git-hook"}
EVENT_POINTS = {
    "SESSION_START": "session-start",
    "PRE_TOOL": "pre-tool-use",
    "POST_TOOL": "post-tool-use",
    "TOOL_FAILURE": "post-tool-use",
    "STOP": "stop",
}
GIT_POINTS = {"commit": "git-commit", "commit-msg": "git-commit", "push": "git-push"}


def engine_points() -> set[str]:
    """Every point the engine wires: surfaces, git script events and the agent events chock uses."""
    from chock.compile.emitters import SCRIPT_EVENTS
    from chock.compile.surface_kinds import Surface

    points = {SURFACE_POINTS.get(s.value, s.value) for s in Surface if s.value not in NOT_DRAWN}
    points |= {GIT_POINTS[event] for event in SCRIPT_EVENTS}
    used = {
        name
        for path in (ROOT / "src" / "chock").rglob("*.py")
        for name in re.findall(r"_contract\.([A-Z_]+)", path.read_text(encoding="utf-8"))
    } & AGENT_EVENTS
    unmapped = used - set(EVENT_POINTS)
    assert not unmapped, f"the engine wires an agent event the figure does not draw: {sorted(unmapped)}"
    return points | {EVENT_POINTS[name] for name in used}


def test_figure_points_equal_the_engine_points_in_session_order() -> None:
    ids = [p["id"] for p in FIGURE["points"]]
    assert set(ids) == engine_points()
    assert len(ids) == len(set(ids))
    assert [p["n"] for p in FIGURE["points"]] == [str(i) for i in range(1, len(ids) + 1)]
    assert ids == [
        "session-start", "ambient-rule", "pre-tool-use", "post-tool-use", "stop", "mcp-gateway",
        "git-commit", "git-push", "ci-gate",
    ]  # fmt: skip


def test_no_prompt_submit_hook_is_wired_so_none_is_drawn() -> None:
    sources = " ".join(p.read_text(encoding="utf-8") for p in (ROOT / "src" / "chock").rglob("*.py"))
    assert "PROMPT_SUBMIT" not in sources
    assert "prompt" not in " ".join(p["id"] for p in FIGURE["points"])


def test_every_point_has_a_scope_and_existing_proving_tests() -> None:
    for point in FIGURE["points"]:
        assert point["scope"] and point["proof"], point["id"]
        for rel in point["proof"]:
            assert (ROOT / rel).is_file(), rel


def test_scopes_say_which_points_depend_on_the_agent() -> None:
    scopes = {p["id"]: p["scope"] for p in FIGURE["points"]}
    for point in ("session-start", "pre-tool-use", "post-tool-use", "stop"):
        assert scopes[point] == "where the agent has hooks", point
    for point in ("git-commit", "git-push"):
        assert scopes[point] == "every agent, and people", point
    assert scopes["ci-gate"] == scopes["ambient-rule"] == "every agent"


def test_components_are_generic_and_the_stops_are_five() -> None:
    shown = {k: v for k, v in FIGURE.items() if k != "_"}
    shown["points"] = [{k: v for k, v in c.items() if k != "proof"} for c in FIGURE["points"]]
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
