"""Surface enum and per-agent capability matrix for compiled policy outputs."""

from __future__ import annotations

from enum import Enum

from chock.compile.levels import IN_AGENT_TODAY, Grade, _matrix_can_block, in_agent_grade
from chock.hooks.in_agent_install import AGENT_HOOKS_VENDORS
from chock.vendors import CHOCK_AGENT

#: Shared by every CLI subcommand that takes a required, non-empty `--agents` option.
AGENTS_ARG_REQUIRED_MSG = "--agents requires at least one agent name"


class Surface(str, Enum):
    AMBIENT_RULE = "ambient-rule"
    GIT_HOOK = "git-hook"
    CI_GATE = "ci-gate"
    PRE_TOOL_USE = "pre-tool-use"
    MANAGED_SETTING = "managed-setting"
    GATEWAY = "gateway"
    MCP_GATEWAY = "mcp-gateway"
    AGENT_HOOKS = "agent-hooks"


#: Derived, never hand-rowed: every aliased agent gets the advisory floor, claude keeps
#: its managed-setting arm (chock policy), and in-agent membership comes from the matrix
#: blocking predicate via IN_AGENT_TODAY -- agent-hooks where the vendor is wired through
#: chock's owned agent-hooks file, pre-tool-use everywhere else.
SURFACE_AGENTS: dict[str, set[Surface]] = {
    agent: {Surface.AMBIENT_RULE, Surface.GIT_HOOK, Surface.CI_GATE} for agent in CHOCK_AGENT
}
SURFACE_AGENTS["claude"].add(Surface.MANAGED_SETTING)

for _agent in IN_AGENT_TODAY:
    if not _matrix_can_block(_agent):  # pragma: no cover - membership already derives from can_block
        raise AssertionError(
            f"agentseam's matrix no longer confirms {_agent!r} can block a pre-tool call; "
            "in-agent membership must be re-derived, not silently kept"
        )
    _surface = Surface.AGENT_HOOKS if CHOCK_AGENT[_agent] in AGENT_HOOKS_VENDORS else Surface.PRE_TOOL_USE
    SURFACE_AGENTS[_agent].add(_surface)
del _agent, _surface


INSTALLED_SURFACES: set[Surface] = {Surface.GIT_HOOK, Surface.CI_GATE, Surface.AMBIENT_RULE}


def coverage_cell(
    emitted: set[Surface],
    agent: str,
    *,
    pre_tool_use_installed: bool = False,
    ci_gate_installed: bool = False,
    agent_hooks_installed: bool = False,
) -> Grade:
    """The enforcement level a policy achieves on an agent, with the evidence bounding it."""
    supported = SURFACE_AGENTS.get(agent, set())
    active = emitted & supported if supported else set()
    if not active:
        return Grade("none", None, False)

    for installed, surface in (
        (pre_tool_use_installed, Surface.PRE_TOOL_USE),
        (agent_hooks_installed, Surface.AGENT_HOOKS),
    ):
        if installed and surface in active and agent in IN_AGENT_TODAY:
            return in_agent_grade(agent, surface.value)
    commit_time = active & INSTALLED_SURFACES & {Surface.GIT_HOOK}
    if ci_gate_installed:
        commit_time |= active & INSTALLED_SURFACES & {Surface.CI_GATE}
    if commit_time:
        return Grade("enforced-at-commit", None, False)
    if Surface.AMBIENT_RULE in active & INSTALLED_SURFACES:
        return Grade("advisory", None, False)
    return Grade("none", None, False)


def coverage_level(
    emitted: set[Surface],
    agent: str,
    *,
    pre_tool_use_installed: bool = False,
    ci_gate_installed: bool = False,
    agent_hooks_installed: bool = False,
) -> str:
    """Return the enforcement level a policy actually achieves on an agent."""
    return coverage_cell(
        emitted,
        agent,
        pre_tool_use_installed=pre_tool_use_installed,
        ci_gate_installed=ci_gate_installed,
        agent_hooks_installed=agent_hooks_installed,
    ).level


def parse_agent_selection(groups: list[str], valid: dict[str, object] | None = None) -> list[str]:
    """Split comma- or space-separated --agents values; reject names not in `valid`."""
    valid = SURFACE_AGENTS if valid is None else valid
    agents: list[str] = []
    for group in groups:
        for raw_name in group.split(","):
            name = raw_name.strip()
            if name and name not in agents:
                agents.append(name)
    unknown = [a for a in agents if a not in valid]
    if unknown:
        raise ValueError(f"unknown agent(s): {', '.join(unknown)} -- valid: {', '.join(sorted(valid))}")
    return agents
