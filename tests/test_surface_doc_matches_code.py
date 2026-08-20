"""The per-agent surface table says it comes from surfaces.py. It has to.

`docs/enforcement-surfaces.md` publishes a matrix of which surfaces each agent supports and
cites `src/chock/compile/surfaces.py` as its source. Nothing checked that, and it
drifted: adding `tabnine` and `vscode` to SURFACE_AGENTS left the table naming eleven agents
while the code supported thirteen.

A table of what is enforced where is the page a reader trusts most, so it is the worst one
to let rot.
"""

from __future__ import annotations

import re
from pathlib import Path

from chock.compile.surfaces import SURFACE_AGENTS, Surface

DOC = Path(__file__).resolve().parents[1] / "docs" / "enforcement-surfaces.md"
COLUMNS = [
    Surface.AMBIENT_RULE,
    Surface.GIT_HOOK,
    Surface.CI_GATE,
    Surface.PRE_TOOL_USE,
    Surface.MANAGED_SETTING,
]
#: Display names that differ from the agent key.
ALIAS = {
    "claude code": "claude",
    "kimi code": "kimi-code",
    "vs code": "vscode",
    "antigravity cli": "antigravity",
}


def _rows() -> dict[str, list[bool]]:
    text = DOC.read_text(encoding="utf-8")
    table = text.split("| Agent | ambient")[1].split("\n\n")[0]
    rows: dict[str, list[bool]] = {}
    for line in table.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) != len(COLUMNS) + 1 or not cells[0] or cells[0].startswith(":-"):
            continue
        name = re.sub(r"\*+", "", cells[0]).lower()
        rows[ALIAS.get(name, name)] = [c == "✅" for c in cells[1:]]
    return rows


def test_table_names_exactly_the_agents_the_code_supports() -> None:
    assert set(_rows()) == set(SURFACE_AGENTS)


def test_every_cell_matches_the_code() -> None:
    wrong = [
        f"{agent}/{surface.value}: table={marked}, code={surface in SURFACE_AGENTS[agent]}"
        for agent, marks in _rows().items()
        if agent in SURFACE_AGENTS
        for surface, marked in zip(COLUMNS, marks)
        if marked != (surface in SURFACE_AGENTS[agent])
    ]
    assert not wrong, "enforcement-surfaces.md disagrees with surfaces.py:\n  " + "\n  ".join(wrong)


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
    assert coverage_level(ci_only, "cursor", ci_gate_installed=False) == "unsupported"
    assert coverage_level(ci_only, "cursor", ci_gate_installed=True) == "enforced-at-commit"
