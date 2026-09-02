"""Vendor wire facts read from agentseam's public surface, plus the one alias table."""

from __future__ import annotations

from typing import Any

from agentseam import adapters as _adapters
from agentseam import contract as _contract
from agentseam import matrix as _matrix
from agentseam.vendor_config import VENDOR_CONFIG

CHOCK_AGENT: dict[str, str] = {
    "claude": "claude_code",
    "cursor": "cursor",
    "windsurf": "windsurf",
    "devin": "devin",
    "codex": "codex_cli",
    "grok": "grok",
    "junie": "junie",
    "kimi-code": "kimi_code",
    "copilot": "vscode_copilot",
    "gemini": "gemini_cli",
    "vscode": "vscode_copilot",
    "aider": "aider",
    "replit": "replit",
    "tabnine": "tabnine",
    "antigravity": "antigravity",
}


def entry(vendor: str) -> dict[str, Any]:
    """agentseam's vendor-config entry for `vendor`; chock reads it, never re-records it."""
    return VENDOR_CONFIG[vendor]


def repo_wirable(vendor: str) -> bool:
    """Whether `chock sync --repo` can reach the vendor's hook config: a repo-relative JSON file.

    A home-anchored config path (junie, kimi_code) or a non-JSON format is outside the
    repo-scoped install model, not outside the vendor's capability; the matrix row still
    says what the vendor could do, this says what chock's installer may touch.
    """
    facts = entry(vendor)
    return facts["config_format"] == "json" and not str(facts["config_path"]).startswith("~")


def in_agent_vendors() -> tuple[str, ...]:
    """Vendors the in-agent surface covers: the matrix blocking predicate, install-capped.

    Capability enters from `agentseam.matrix` only; the vendor entry contributes wire
    facts (and the install cap above), never capability.
    """
    return tuple(sorted(v for v in VENDOR_CONFIG if _matrix.can_block(v, _contract.PRE_TOOL) and repo_wirable(v)))


def config_path(vendor: str) -> str:
    """Repo-relative path of the file the vendor reads hook wiring from."""
    return str(entry(vendor)["config_path"])


def wire_event(vendor: str, canonical: str) -> str:
    """The vendor's wire spelling of one of agentseam's canonical events."""
    return str(_adapters.get(vendor).REVERSE_EVENT_MAP[canonical])


def pre_tool_event(vendor: str) -> str:
    """The vendor's wire spelling of the pre-tool gate event."""
    return wire_event(vendor, _contract.PRE_TOOL)


def shell_gate_event(vendor: str) -> str:
    """The wire event a shell-command gate registers under (cursor gates shell directly)."""
    verdicts = entry(vendor).get("verdicts") or {}
    return str(verdicts.get("default_wire_event") or pre_tool_event(vendor))


def shell_matcher(vendor: str) -> str | None:
    """Matcher over the vendor's recorded shell-tool vocabulary, or None where unrecorded."""
    tools = _adapters.shell_tools(vendor)
    return "|".join(tools) if tools else None


def pre_tool_hook_config(vendor: str, command: str, matcher: str | None = None) -> dict[str, Any]:
    """The vendor's complete hook-config document gating pre-tool with `command`."""
    return _adapters.get(vendor).hook_config((_contract.PRE_TOOL,), command, matcher)


def config_envelope(vendor: str) -> dict[str, Any]:
    """Wrapper keys the vendor's hook config carries beside its hooks table."""
    return {key: value for key, value in _adapters.get(vendor).hook_config((), "").items() if key != "hooks"}
