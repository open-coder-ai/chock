"""Every per-agent surface table says it comes from surfaces.py. Each one has to.

`docs/enforcement-surfaces.md` publishes a matrix of which surfaces each agent supports and
cites `src/chock/compile/surfaces.py` as its source. Nothing checked that, and it
drifted: adding `tabnine` and `vscode` to SURFACE_AGENTS left the table naming eleven agents
while the code supported thirteen.

A table of what is enforced where is the page a reader trusts most, so it is the worst one
to let rot. `README.md` now carries a condensed copy of the same matrix -- the copy a
reader reaches first and the one most likely to be quoted back at us -- so it is checked
against the same source, cell by cell, rather than trusted because it was right once.

The page publishes a SECOND table nothing checked: the coverage levels themselves, and their
strength order. That is the vocabulary every other claim is worded in, so a level the code
can report and the page does not name -- or an order the page states and `level_rank` does
not -- is a bigger lie than a stale checkmark. Both are bound below.
"""

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
    # agent-hooks joined the table with 0.4.0's docs sweep; listing it here means
    # test_every_cell_matches_the_code now verifies that column against surfaces.py too.
    Surface.AGENT_HOOKS,
]
#: The README publishes the same rows without `managed-setting`: that surface is compiled and
#: never installed, so a checkmark on the page a reader skims would read as a live control.
#: Dropping the column is only honest while the README says why -- see
#: test_readme_says_why_the_absent_surfaces_are_absent.
README_COLUMNS = [c for c in COLUMNS if c is not Surface.MANAGED_SETTING]
#: Headings that abbreviate the surface's own name. Kept explicit rather than matched loosely,
#: so a heading that drifts to something else entirely still fails instead of passing as a synonym.
HEADING = {Surface.AMBIENT_RULE: "ambient"}
#: Display names that differ from the agent key.
ALIAS = {
    "claude code": "claude",
    "kimi code": "kimi-code",
    "vs code": "vscode",
    "antigravity cli": "antigravity",
}


def _rows(path: Path, columns: list[Surface]) -> dict[str, list[bool]]:
    """Parse one published matrix into {agent: [supported, per column in `columns`]}.

    The header row is checked, not skipped. An earlier version split on a fixed prefix and read
    the body against the column list kept here, which made the headings decorative: swapping two
    of them -- and changing nothing else -- left every cell "matching" a column it no longer sat
    under. That publishes a false enforcement claim while every test still passes, which is worse
    than an unchecked table, because the check is what a reader trusts.
    """
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
    """Both publications list every supported agent and no others.

    This is the drift that actually happened: `tabnine` and `vscode` joined SURFACE_AGENTS and the
    docs table kept naming eleven. A reader checking whether their agent is covered reads the
    table, so an agent missing from it is indistinguishable from an agent we do not support.
    """
    assert set(_rows(path, columns)) == set(SURFACE_AGENTS)


@pytest.mark.parametrize(("path", "columns"), TABLES, ids=lambda v: getattr(v, "name", ""))
def test_every_cell_matches_the_code(path: Path, columns: list[Surface]) -> None:
    """Every checkmark, in either publication, is a claim `surfaces.py` still makes.

    Naming the right agents is not enough: the cell is the claim a reader acts on, and a stale
    tick reads as a control that is switched on.
    """
    wrong = [
        f"{agent}/{surface.value}: table={marked}, code={surface in SURFACE_AGENTS[agent]}"
        for agent, marks in _rows(path, columns).items()
        if agent in SURFACE_AGENTS
        for surface, marked in zip(columns, marks)
        if marked != (surface in SURFACE_AGENTS[agent])
    ]
    assert not wrong, f"{path.name} disagrees with surfaces.py:\n  " + "\n  ".join(wrong)


def _omission_caveat() -> str:
    """The one README paragraph that says why three surfaces are missing from its table.

    Scoped to that paragraph, and whitespace-flattened so a rewrap does not read as a deletion.
    Searching the whole file instead let the caveat be deleted outright while the phrases
    survived somewhere else -- a comment, a changelog line -- and the test still passed.
    """
    # Flatten first, then look: searching the raw text meant a rewrap that split the anchor
    # phrase across two lines read as a deleted caveat. The check has to survive an edit that
    # changes nothing but line breaks, or it trains people to work around it.
    paragraphs = [" ".join(p.split()) for p in README.read_text(encoding="utf-8").split("\n\n")]
    found = [p for p in paragraphs if "surfaces are absent" in p]
    assert len(found) == 1, f"expected exactly one omission caveat, found {len(found)}"
    return found[0]


def _reason_for(caveat: str, surface: Surface) -> str:
    """The slice of `caveat` that belongs to `surface`: its name up to the next surface named.

    Membership in the paragraph is not enough. Every reason here is true of exactly one surface,
    so three correct phrases attached to the wrong three surfaces is a page of false statements
    that a whole-paragraph search waves through. Backticks delimit the names, which is also what
    keeps `gateway` from matching inside `mcp-gateway`.
    """
    marks = sorted(
        (caveat.index(f"`{s.value}`"), s) for s in (Surface.MANAGED_SETTING, Surface.GATEWAY, Surface.MCP_GATEWAY)
    )
    for i, (start, at) in enumerate(marks):
        if at is surface:
            return caveat[start : marks[i + 1][0] if i + 1 < len(marks) else len(caveat)]
    raise AssertionError(f"{surface.value} is not named in the caveat")


def test_readme_says_why_the_absent_surfaces_are_absent() -> None:
    """Dropping a column is a claim of its own: the reader has to be told, not left to notice.

    The README's condensed table shows five surfaces and gives, for each of the three it omits,
    the reason that one credits no agent today. Every reason is a fact about the code, so every
    reason is checked here -- if an installer or an emitter lands, the omission becomes the lie,
    and this fails then rather than only when someone deletes the note.
    """
    from chock.compile.compiler import EMITTERS
    from chock.compile.surfaces import INSTALLED_SURFACES, coverage_level

    #: The stated reason for each omission, and the phrase the README carries it in.
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
        # Necessary, not sufficient: a policy emitting only this surface grades `none` for every
        # agent. Necessary because that is the claim; not sufficient because a witness-gated
        # surface (`pre-tool-use` with no install) also grades `none` while genuinely belonging
        # in the table. So each phrase's own narrower fact is pinned separately below.
        crediting = [a for a in SURFACE_AGENTS if coverage_level({surface}, a) != "none"]
        assert not crediting, f"{surface.value} now credits {crediting}; the README owes it a column"

    assert Surface.MANAGED_SETTING not in INSTALLED_SURFACES, "an installer landed; 'not installed' is now false"
    assert Surface.GATEWAY not in EMITTERS, "gateway emits now; 'not yet emitted' is now false"
    # `mcp-gateway` is the one whose reason an installer would NOT falsify: it is emitted today
    # and an installer could ship before the per-client witnesses do, while the surface still
    # credits nobody. What carries that wording is its absence from every agent's supported set,
    # which is also what `coverage_level` reads -- so pin the structural fact, not the installer.
    supporting = [a for a, s in SURFACE_AGENTS.items() if Surface.MCP_GATEWAY in s]
    assert not supporting, f"mcp-gateway is now supported by {supporting}; the per-client wording is stale"


def _published_levels() -> list[str]:
    """The level names the doc's `| Level | Meaning |` table publishes, in the order it lists them.

    Read from the first column's bolded code span, so a row whose *meaning* is rewritten still
    matches while a row whose *name* changes does not. Order is kept because the table's order
    is itself a published claim -- it is what a reader takes the ranking from.
    """
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
    """The level vocabulary is what every other claim on the page is worded in.

    A level the compiler can write into `.chock/coverage.json` and the page does not name
    leaves a reader with a verdict they cannot look up; a level the page names and the code
    cannot produce is a control we are advertising and do not have. Both directions fail here,
    which is why this compares sets rather than checking presence.
    """
    assert set(_published_levels()) == set(COVERAGE_LEVELS), (
        f"the page publishes {sorted(_published_levels())}, the code reports {sorted(COVERAGE_LEVELS)}"
    )


def test_the_page_lists_the_in_agent_ladder_strongest_first() -> None:
    """The table's ORDER is a claim about strength, so it is bound to `level_rank`.

    Naming the right levels is not enough. A reader takes the ranking from the order the rows
    appear in, so a table that lists `best-effort` above `enforceable` teaches the ladder
    backwards while every name still checks out. Only the ranked levels are constrained --
    `enforced-at-commit`, `advisory` and `disabled` have no rank, so the page may place them
    wherever reads best.
    """
    ranked = [level for level in _published_levels() if level in IN_AGENT_LEVELS]
    ranks = [level_rank(level) for level in ranked]
    assert ranks == sorted(ranks, reverse=True), (
        f"the page lists the ladder as {ranked}, which is not strongest-first by level_rank"
    )


def test_the_page_states_the_ladder_order_the_code_returns() -> None:
    """The page prints the ladder as one line; it has to be the line `level_rank` produces.

    Written out because the table alone cannot show `detect`, which has a rank but is never a
    verdict here. Rendered from the code and compared, so a hand-typed reordering fails.
    """
    rendered = "  <  ".join(sorted(IN_AGENT_LEVELS, key=level_rank))
    flattened = " ".join(DOC.read_text(encoding="utf-8").split())
    assert " ".join(rendered.split()) in flattened, f"the page does not state the ladder as: {rendered}"


def test_managed_setting_is_disclosed_as_not_installed() -> None:
    """The table marks it supported; nothing installs it, and the page must say so.

    Without the caveat a reader takes the checkmark as a control that is switched on.
    """
    assert Surface.MANAGED_SETTING in SURFACE_AGENTS["claude"], "table caveat is now stale"
    from chock.compile.surfaces import INSTALLED_SURFACES

    assert Surface.MANAGED_SETTING not in INSTALLED_SURFACES, "an installer landed; drop the caveat"
    assert "compiled but not installed" in DOC.read_text(encoding="utf-8")


def test_ci_gate_is_disclosed_as_needing_its_installer() -> None:
    """`ci-gate` is the surface this page was most wrong about, so it stays pinned.

    It was once documented as the "hard, un-bypassable" backstop and listed in
    INSTALLED_SURFACES while nothing installed it and the step it emitted could not fail.
    It now emits a step that can fail and has an installer, so the earlier assertion --
    that it must NOT be emitted -- has been satisfied out of existence.

    What replaces it is the claim that is true today and could drift tomorrow: emitting is
    not enforcing. `install-ci` has to have written the workflow before coverage credits
    the surface, and the page has to say so, exactly as it does for `pre-tool-use`.
    """
    from chock.compile.compiler import EMITTERS
    from chock.compile.surfaces import INSTALLED_SURFACES, coverage_level

    assert Surface.CI_GATE in EMITTERS, "the surface is documented as emitting; it must emit"
    assert Surface.CI_GATE in INSTALLED_SURFACES, "an installer exists; the constant must reflect it"
    assert "install-ci" in DOC.read_text(encoding="utf-8"), "the page must name what wires the surface up"

    # The witness itself: a CI-only policy claims nothing until the workflow is installed.
    ci_only = {Surface.CI_GATE}
    assert coverage_level(ci_only, "cursor", ci_gate_installed=False) == "none"
    assert coverage_level(ci_only, "cursor", ci_gate_installed=True) == "enforced-at-commit"
