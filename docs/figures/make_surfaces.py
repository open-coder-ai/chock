"""chock's own figure: one policy, fanned into the enforcement surfaces it compiles to.

Every count below is read from the package, never typed: `Surface` is the enum
`chock.compile.surfaces` defines, `SURFACE_AGENTS` is its derived agent-to-surface map (built
from `agentseam`'s verified capability matrix, never hand-rowed -- see that module's docstring),
and `CHOCK_AGENT` is the one alias table chock keeps. The three enforcement tiers and the short
phrase on each surface are this script's own words, same as `make_family.py`'s `ROLES` fragments
-- English a human authored, sitting beside numbers the code computed.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import palette as p

from chock.compile.surfaces import SURFACE_AGENTS, Surface
from chock.vendors import CHOCK_AGENT

W, H = 760, 500
NAME, COUNT, TIER = 13, 12, 12

#: Tier index into `palette.ENFORCEMENT`, or None for a surface no agent currently reaches
#: (drawn in `palette.NEUTRAL` instead -- absence is never the pale end of a ramp).
TIER_INDEX = {
    Surface.AMBIENT_RULE: 0,
    Surface.GIT_HOOK: 1,
    Surface.CI_GATE: 1,
    Surface.PRE_TOOL_USE: 2,
    Surface.AGENT_HOOKS: 2,
    Surface.MANAGED_SETTING: None,
    Surface.GATEWAY: None,
    Surface.MCP_GATEWAY: None,
}

#: The honest word for each surface: what it does, or why it currently reaches no one.
PHRASE = {
    Surface.AMBIENT_RULE: "advisory only",
    Surface.GIT_HOOK: "enforced at commit",
    Surface.CI_GATE: "enforced at commit",
    Surface.PRE_TOOL_USE: "enforced in-agent",
    Surface.AGENT_HOOKS: "enforced in-agent",
    Surface.MANAGED_SETTING: "compiled, not installed",
    Surface.GATEWAY: "modelled, not emitted",
    Surface.MCP_GATEWAY: "emits, not yet credited",
}

TIER_NAME = ("advisory", "enforced at commit", "enforced in-agent")

#: Reading order: the four surfaces every agent (or most) reach, then the four named for
#: honesty even though today either two agents (agent-hooks) or none reach them.
ROW1 = [Surface.AMBIENT_RULE, Surface.GIT_HOOK, Surface.CI_GATE, Surface.PRE_TOOL_USE]
ROW2 = [Surface.AGENT_HOOKS, Surface.MANAGED_SETTING, Surface.GATEWAY, Surface.MCP_GATEWAY]

COLS = [104, 288, 472, 656]  # column centres; 168-wide boxes, 16px gaps, 20px margins
BOX_W, BOX_H = 168, 100
ROW1_Y, ROW2_Y = 150, 290
BUS1_Y, BUS2_Y = 115, 270
POLICY_X, POLICY_Y, POLICY_W, POLICY_H = 20, 20, 720, 70


def _wire(x1, y1, x2, y2, colour):
    """A plain connector: distribution wiring, not a claim, so it carries no arrowhead."""
    return '  <line x1="%g" y1="%g" x2="%g" y2="%g" stroke="%s" stroke-width="%d"/>\n' % (
        x1,
        y1,
        x2,
        y2,
        colour,
        p.STROKE_WIDTH,
    )


def _surface_count(surface):
    """How many of chock's agent names carry `surface`, derived from SURFACE_AGENTS."""
    return sum(1 for agent in SURFACE_AGENTS if surface in SURFACE_AGENTS[agent])


def _node(cx, y, surface, t):
    """One surface box: name, agent count, and the tier word -- colour is never the only carrier."""
    idx = TIER_INDEX[surface]
    accent = t["enforcement"][idx] if idx is not None else t["neutral"]
    x = cx - BOX_W / 2
    n = _surface_count(surface)
    out = p.box(x, y, BOX_W, BOX_H, t["surface"], accent)
    out += p.box(x, y, BOX_W, 5, accent, rx=0)  # tier chip, redundant with the word below
    out += p.text(x + 12, y + 26, surface.value, t["text"], NAME, p.MONO, "600")
    out += p.text(x + 12, y + 46, f"{n} agent{'' if n == 1 else 's'}", t["secondary"], COUNT)
    out += p.text(x + 12, y + 66, PHRASE[surface], accent, TIER, weight="600")
    out += p.arrow(cx, y - 20, cx, y, accent)
    return out


def render(t, name):
    a = t["enforcement"][1]
    n_names = len(CHOCK_AGENT)
    n_vendors = len(set(CHOCK_AGENT.values()))
    svg = p.open_svg(
        W,
        H,
        t,
        "One policy, eight surfaces",
        "A fan-out diagram: one chock policy compiles into eight enforcement surfaces. "
        "All 15 supported agent names get the advisory ambient rule and the two commit-time "
        "gates, git hook and CI gate. 9 also get a native pre-tool-use hook, enforced live in "
        "the agent, and 2 (vscode, copilot -- one underlying vendor) get chock's own "
        "agent-hooks file, also enforced in-agent. Three surfaces are named for honesty though "
        "no agent reaches them yet: managed-setting is compiled for Claude but not installed, "
        "gateway is modelled but not emitted, and mcp-gateway emits but is not yet credited to "
        "any agent.",
    )

    svg += p.box(POLICY_X, POLICY_Y, POLICY_W, POLICY_H, t["surface"], a)
    svg += p.text(POLICY_X + 16, POLICY_Y + 28, "one policy", t["text"], 15, p.MONO, "600")
    svg += p.text(
        POLICY_X + 16,
        POLICY_Y + 48,
        ".agents/policies/<id>/manifest.yaml -- compiled by chock.compile.compiler",
        t["secondary"],
        12,
    )

    cx = (COLS[0] + COLS[-1]) / 2
    svg += _wire(cx, POLICY_Y + POLICY_H, cx, BUS1_Y, a)
    svg += _wire(COLS[0], BUS1_Y, COLS[-1], BUS1_Y, a)
    for x, surface in zip(COLS, ROW1, strict=True):
        svg += _node(x, ROW1_Y, surface, t)

    svg += _wire(cx, BUS1_Y, cx, BUS2_Y, a)
    svg += _wire(COLS[0], BUS2_Y, COLS[-1], BUS2_Y, a)
    for x, surface in zip(COLS, ROW2, strict=True):
        svg += _node(x, ROW2_Y, surface, t)

    legend_y = 410
    svg += p.text(20, legend_y, "Fill:", t["secondary"], 12, weight="600")
    lx = 70
    for i, label in enumerate(TIER_NAME):
        svg += p.box(lx, legend_y - 12, 14, 14, t["enforcement"][i])
        svg += p.text(lx + 20, legend_y, label, t["text"], 12)
        lx += 20 + len(label) * 7 + 24
    svg += p.box(lx, legend_y - 12, 14, 14, t["neutral"])
    svg += p.text(lx + 20, legend_y, "absent (reaches no agent yet)", t["text"], 12)

    svg += p.text(
        20,
        legend_y + 30,
        f"{n_names} chock agent names map to {n_vendors} agentseam vendors (vscode and copilot share vscode_copilot).",
        t["secondary"],
        12,
    )

    return svg + p.close_svg()


if __name__ == "__main__":
    for path in p.write_pair("surfaces", render):
        print("wrote", path)
