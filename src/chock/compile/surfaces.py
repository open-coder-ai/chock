"""Surface enum and per-agent capability matrix for compiled policy outputs."""

from __future__ import annotations

from enum import Enum

from chock.compile.levels import MATRIX_AGENT, _matrix_can_block, in_agent_level


class Surface(str, Enum):
    AMBIENT_RULE = "ambient-rule"
    GIT_HOOK = "git-hook"
    CI_GATE = "ci-gate"
    PRE_TOOL_USE = "pre-tool-use"
    MANAGED_SETTING = "managed-setting"
    GATEWAY = "gateway"
    MCP_GATEWAY = "mcp-gateway"
    AGENT_HOOKS = "agent-hooks"


SURFACE_AGENTS: dict[str, set[Surface]] = {
    "claude": {
        Surface.AMBIENT_RULE,
        Surface.GIT_HOOK,
        Surface.CI_GATE,
        Surface.MANAGED_SETTING,
    },
    "cursor": {Surface.AMBIENT_RULE, Surface.GIT_HOOK, Surface.CI_GATE},
    "copilot": {Surface.AMBIENT_RULE, Surface.GIT_HOOK, Surface.CI_GATE},
    "windsurf": {Surface.AMBIENT_RULE, Surface.GIT_HOOK, Surface.CI_GATE},
    "devin": {Surface.AMBIENT_RULE, Surface.GIT_HOOK, Surface.CI_GATE},
    "codex": {Surface.AMBIENT_RULE, Surface.GIT_HOOK, Surface.CI_GATE},
    "grok": {Surface.AMBIENT_RULE, Surface.GIT_HOOK, Surface.CI_GATE},
    "kimi-code": {Surface.AMBIENT_RULE, Surface.GIT_HOOK, Surface.CI_GATE},
    "aider": {Surface.AMBIENT_RULE, Surface.GIT_HOOK, Surface.CI_GATE},
    "gemini": {Surface.AMBIENT_RULE, Surface.GIT_HOOK, Surface.CI_GATE},
    "replit": {Surface.AMBIENT_RULE, Surface.GIT_HOOK, Surface.CI_GATE},
    "tabnine": {Surface.AMBIENT_RULE, Surface.GIT_HOOK, Surface.CI_GATE},
    "vscode": {Surface.AMBIENT_RULE, Surface.GIT_HOOK, Surface.CI_GATE},
    "antigravity": {Surface.AMBIENT_RULE, Surface.GIT_HOOK, Surface.CI_GATE},
}


for _agent, _surface in (
    ("claude", Surface.PRE_TOOL_USE),
    ("cursor", Surface.PRE_TOOL_USE),
    ("copilot", Surface.AGENT_HOOKS),
    ("vscode", Surface.AGENT_HOOKS),
):
    if not _matrix_can_block(_agent):
        raise AssertionError(
            f"agentseam's matrix no longer confirms {_agent!r} can block a pre-tool call; "
            f"{_surface.value} membership here must be re-reviewed, not silently kept or dropped"
        )
    SURFACE_AGENTS[_agent].add(_surface)
del _agent, _surface


INSTALLED_SURFACES: set[Surface] = {Surface.GIT_HOOK, Surface.CI_GATE, Surface.AMBIENT_RULE}


def coverage_level(
    emitted: set[Surface],
    agent: str,
    *,
    pre_tool_use_installed: bool = False,
    ci_gate_installed: bool = False,
    agent_hooks_installed: bool = False,
) -> str:
    """Return the enforcement level a policy actually achieves on an agent."""
    supported = SURFACE_AGENTS.get(agent, set())
    if not supported:
        return "none"

    active = emitted & supported
    if not active:
        return "none"

    if pre_tool_use_installed and Surface.PRE_TOOL_USE in active:
        if MATRIX_AGENT.get(agent):
            return in_agent_level(agent)
    if agent_hooks_installed and Surface.AGENT_HOOKS in active:
        if MATRIX_AGENT.get(agent):
            return in_agent_level(agent)
    commit_time = active & INSTALLED_SURFACES & {Surface.GIT_HOOK}
    if ci_gate_installed:
        commit_time |= active & INSTALLED_SURFACES & {Surface.CI_GATE}
    if commit_time:
        return "enforced-at-commit"
    if Surface.AMBIENT_RULE in active & INSTALLED_SURFACES:
        return "advisory"
    return "none"


def parse_agent_selection(groups: list[str], valid: dict[str, object] | None = None) -> list[str]:
    """Split comma- or space-separated --agents values; reject names not in `valid`."""
    valid = SURFACE_AGENTS if valid is None else valid
    agents: list[str] = []
    for group in groups:
        for name in group.split(","):
            name = name.strip()
            if name and name not in agents:
                agents.append(name)
    unknown = [a for a in agents if a not in valid]
    if unknown:
        raise ValueError(f"unknown agent(s): {', '.join(unknown)} -- valid: {', '.join(sorted(valid))}")
    return agents
