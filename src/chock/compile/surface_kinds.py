"""The surface vocabulary alone, with no dependencies, so naming one costs no imports.

Held apart from `surfaces`, which derives per-agent membership and therefore reaches the
installer and the vendor matrix. A module that only needs to say "ambient-rule" should not
pull that in behind it -- doing so is what made config, the gate builder and the in-agent
emitter into an import cycle.
"""

from __future__ import annotations

from enum import Enum


class Surface(str, Enum):
    AMBIENT_RULE = "ambient-rule"
    GIT_HOOK = "git-hook"
    CI_GATE = "ci-gate"
    PRE_TOOL_USE = "pre-tool-use"
    STOP = "stop"
    PROMPT_SUBMIT = "prompt-submit"
    MANAGED_SETTING = "managed-setting"
    GATEWAY = "gateway"
    MCP_GATEWAY = "mcp-gateway"
    AGENT_HOOKS = "agent-hooks"
