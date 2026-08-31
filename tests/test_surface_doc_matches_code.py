"""Every per-agent surface table says it comes from surfaces.py. Each one has to."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from chock.compile.levels import COVERAGE_LEVELS, IN_AGENT_LEVELS, level_rank
from chock.compile.surfaces import SURFACE_AGENTS, Surface

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "enforcement-surfaces.md"
README = ROOT / "README.md"
COLUMNS = [
    Surface.AMBIENT_RULE,
    Surface.GIT_HOOK,
    Surface.CI_GATE,
    Surface.PRE_TOOL_USE,
    Surface.MANAGED_SETTING,
    Surface.AGENT_HOOKS,
]
README_COLUMNS = [c for c in COLUMNS if c is not Surface.MANAGED_SETTING]
HEADING = {Surface.AMBIENT_RULE: "ambient"}
ALIAS = {
    "claude code": "claude",
    "kimi code": "kimi-code",
    "vs code": "vscode",
    "antigravity cli": "antigravity",
}


def _rows(path: Path, columns: list[Surface]) -> dict[str, list[bool]]:
    """Parse one published matrix into {agent: [supported, per column in `columns`]}."""
    text = path.read_text(encoding="utf-8")
    start = "| Agent | ambient"
    table = start + text.split(start)[1].split("\n\n")[0]
    header, *body = table.splitlines()
    named = [c.strip() for c in header.strip().strip("|").split("|")][1:]
    expected = [HEADING.get(c, c.value) for c in columns]
    assert named == expected, (
        f"{path.name} heads its columns {named}, not {expected}; "
        "the cells beneath them now mean something other than what this test checks"
    )
    rows: dict[str, list[bool]] = {}
    for line in body:
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) != len(columns) + 1 or not cells[0] or cells[0].startswith(":-"):
            continue
        name = re.sub(r"\*+", "", cells[0]).lower()
        rows[ALIAS.get(name, name)] = [c == "✅" for c in cells[1:]]
    assert rows, f"{path.name} matrix not parsed -- header or column count changed without updating COLUMNS"
    return rows


TABLES = [(DOC, COLUMNS), (README, README_COLUMNS)]


@pytest.mark.parametrize(("path", "columns"), TABLES, ids=lambda v: getattr(v, "name", ""))
def test_table_names_exactly_the_agents_the_code_supports(path: Path, columns: list[Surface]) -> None:
    """Both publications list every supported agent and no others."""
    assert set(_rows(path, columns)) == set(SURFACE_AGENTS)


@pytest.mark.parametrize(("path", "columns"), TABLES, ids=lambda v: getattr(v, "name", ""))
def test_every_cell_matches_the_code(path: Path, columns: list[Surface]) -> None:
    """Every checkmark, in either publication, is a claim `surfaces.py` still makes."""
    wrong = [
        f"{agent}/{surface.value}: table={marked}, code={surface in SURFACE_AGENTS[agent]}"
        for agent, marks in _rows(path, columns).items()
        if agent in SURFACE_AGENTS
        for surface, marked in zip(columns, marks)
        if marked != (surface in SURFACE_AGENTS[agent])
    ]
    assert not wrong, f"{path.name} disagrees with surfaces.py:\n  " + "\n  ".join(wrong)


def _omission_caveat() -> str:
    """The one README paragraph that says why three surfaces are missing from its table."""
    paragraphs = [" ".join(p.split()) for p in README.read_text(encoding="utf-8").split("\n\n")]
    found = [p for p in paragraphs if "surfaces are absent" in p]
    assert len(found) == 1, f"expected exactly one omission caveat, found {len(found)}"
    return found[0]


def _reason_for(caveat: str, surface: Surface) -> str:
    """The slice of `caveat` that belongs to `surface`: its name up to the next surface named."""
    marks = sorted(
        (caveat.index(f"`{s.value}`"), s) for s in (Surface.MANAGED_SETTING, Surface.GATEWAY, Surface.MCP_GATEWAY)
    )
    for i, (start, at) in enumerate(marks):
        if at is surface:
            return caveat[start : marks[i + 1][0] if i + 1 < len(marks) else len(caveat)]
    raise AssertionError(f"{surface.value} is not named in the caveat")


def test_readme_says_why_the_absent_surfaces_are_absent() -> None:
    """Dropping a column is a claim of its own: the reader has to be told, not left to notice."""
    from chock.compile.compiler import EMITTERS
    from chock.compile.surfaces import INSTALLED_SURFACES, coverage_level

    omitted = {
        Surface.MANAGED_SETTING: "compiled but not installed",
        Surface.GATEWAY: "modelled but not yet emitted",
        Surface.MCP_GATEWAY: "per-client witness",
    }
    caveat = _omission_caveat()
    for surface, phrase in omitted.items():
        assert phrase in _reason_for(caveat, surface), (
            f"the caveat no longer gives `{surface.value}` the reason {phrase!r}"
        )
    for surface in omitted:
        crediting = [a for a in SURFACE_AGENTS if coverage_level({surface}, a) != "none"]
        assert not crediting, f"{surface.value} now credits {crediting}; the README owes it a column"

    assert Surface.MANAGED_SETTING not in INSTALLED_SURFACES, "an installer landed; 'not installed' is now false"
    assert Surface.GATEWAY not in EMITTERS, "gateway emits now; 'not yet emitted' is now false"
    supporting = [a for a, s in SURFACE_AGENTS.items() if Surface.MCP_GATEWAY in s]
    assert not supporting, f"mcp-gateway is now supported by {supporting}; the per-client wording is stale"


def _published_levels() -> list[str]:
    """The level names the doc's `| Level | Meaning |` table publishes, in the order it lists them."""
    text = DOC.read_text(encoding="utf-8")
    start = "| Level | Meaning |"
    assert start in text, "the coverage-level table is gone or its header changed"
    table = start + text.split(start)[1].split("\n\n")[0]
    levels = []
    for line in table.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) != 2 or cells[0].startswith(":-") or cells[0] == "Level":
            continue
        found = re.findall(r"`([^`]+)`", cells[0])
        assert len(found) == 1, f"level cell {cells[0]!r} does not name exactly one level"
        levels.append(found[0])
    assert levels, "coverage-level table not parsed -- the row shape changed"
    return levels


def test_the_page_names_every_level_the_code_can_report() -> None:
    """The level vocabulary is what every other claim on the page is worded in."""
    assert set(_published_levels()) == set(COVERAGE_LEVELS), (
        f"the page publishes {sorted(_published_levels())}, the code reports {sorted(COVERAGE_LEVELS)}"
    )


def test_the_page_lists_the_in_agent_ladder_strongest_first() -> None:
    """The table's ORDER is a claim about strength, so it is bound to `level_rank`."""
    ranked = [level for level in _published_levels() if level in IN_AGENT_LEVELS]
    ranks = [level_rank(level) for level in ranked]
    assert ranks == sorted(ranks, reverse=True), (
        f"the page lists the ladder as {ranked}, which is not strongest-first by level_rank"
    )


def test_the_page_states_the_ladder_order_the_code_returns() -> None:
    """The page prints the ladder as one line; it has to be the line `level_rank` produces."""
    rendered = "  <  ".join(sorted(IN_AGENT_LEVELS, key=level_rank))
    flattened = " ".join(DOC.read_text(encoding="utf-8").split())
    assert " ".join(rendered.split()) in flattened, f"the page does not state the ladder as: {rendered}"


def test_managed_setting_is_disclosed_as_not_installed() -> None:
    """The table marks it supported; nothing installs it, and the page must say so."""
    assert Surface.MANAGED_SETTING in SURFACE_AGENTS["claude"], "table caveat is now stale"
    from chock.compile.surfaces import INSTALLED_SURFACES

    assert Surface.MANAGED_SETTING not in INSTALLED_SURFACES, "an installer landed; drop the caveat"
    assert "compiled but not installed" in DOC.read_text(encoding="utf-8")


def test_ci_gate_is_disclosed_as_needing_its_installer() -> None:
    """`ci-gate` is the surface this page was most wrong about, so it stays pinned."""
    from chock.compile.compiler import EMITTERS
    from chock.compile.surfaces import INSTALLED_SURFACES, coverage_level

    assert Surface.CI_GATE in EMITTERS, "the surface is documented as emitting; it must emit"
    assert Surface.CI_GATE in INSTALLED_SURFACES, "an installer exists; the constant must reflect it"
    assert "install-ci" in DOC.read_text(encoding="utf-8"), "the page must name what wires the surface up"

    ci_only = {Surface.CI_GATE}
    assert coverage_level(ci_only, "cursor", ci_gate_installed=False) == "none"
    assert coverage_level(ci_only, "cursor", ci_gate_installed=True) == "enforced-at-commit"
