"""The enforcement-level vocabulary, its strength order, and how a level is derived."""

from __future__ import annotations

from agentseam import contract as _contract
from agentseam import matrix as _matrix

MATRIX_AGENT = {
    "claude": "claude_code",
    "cursor": "cursor",
    "copilot": "vscode_copilot",
    "vscode": "vscode_copilot",
}


def _matrix_can_block(chock_agent: str) -> bool:
    """Whether agentseam's verified matrix confirms `chock_agent` can block a pre-tool call."""
    mapped = MATRIX_AGENT.get(chock_agent)
    return bool(mapped) and _matrix.can_block(mapped, _contract.PRE_TOOL)


DISABLED = "disabled"


DEGRADES_TO_ALLOW = "allow"
DEGRADES_TO_ASK = "ask"
DEGRADES_TO_DENY = "deny"
DEGRADATION_MODES = (DEGRADES_TO_ALLOW, DEGRADES_TO_ASK, DEGRADES_TO_DENY)


CONTROL_DEGRADES_TO = DEGRADES_TO_ALLOW


IN_AGENT_LEVELS = ("none", "detect", "best-effort", "fail-to-ask", "enforceable", "enforced")

UNRANKED_LEVELS = ("enforced-at-commit", "advisory", DISABLED)

UNREPORTABLE_LEVELS = ("detect",)

COVERAGE_LEVELS = (
    *(level for level in IN_AGENT_LEVELS if level not in UNREPORTABLE_LEVELS),
    *UNRANKED_LEVELS,
)


def level_rank(level: str) -> int:
    """Position of `level` in the in-agent strength ladder; higher is stronger."""
    try:
        return IN_AGENT_LEVELS.index(level)
    except ValueError:
        raise ValueError(
            f"{level!r} has no rank on the in-agent ladder {IN_AGENT_LEVELS}; "
            f"{UNRANKED_LEVELS} describe different mechanisms and are deliberately unranked"
        ) from None


def in_agent_level(agent: str, *, degrades_to: str = CONTROL_DEGRADES_TO) -> str:
    """The honest word for an INSTALLED in-agent pre-execution control on `agent`."""
    if degrades_to not in DEGRADATION_MODES:
        raise ValueError(f"unknown degradation mode {degrades_to!r}; expected one of {DEGRADATION_MODES}")
    mapped = MATRIX_AGENT.get(agent)
    if not mapped:
        return "none"
    host = _matrix.enforcement_level(mapped, _contract.PRE_TOOL)
    if host != "best-effort" or degrades_to == DEGRADES_TO_ALLOW:
        return host
    return "fail-to-ask"
