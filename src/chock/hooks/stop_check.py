"""The repo stop's own pre-tool hook (`chock stop`): one entry per client, no matcher, whatever policies are installed.

The runtime refuses every tool call while a stop reaches the agent, reads included, so it must run on every tool
call; a policy's hook runs only for the tools its matcher names. Unstopped, it allows and writes nothing of its own.
"""

from __future__ import annotations

from typing import Any

from chock import vendors
from chock.compile.emitters.in_agent_hooks import (
    copilot_entry,
    cursor_entry,
    generic_pre_tool_config,
    hook_entry,
)
from chock.gate.runner.halt import HALT_HOOK_FLAG
from chock.hooks import heartbeat
from chock.hooks.launch import hook_command
from chock.hooks.runtime_vendor import runtime_rel

STOP_CHECK_FLAG = HALT_HOOK_FLAG


def command(vendor: str) -> str:
    """The repo-relative command running `vendor`'s runtime as the stop check alone."""
    return hook_command(runtime_rel(vendor).as_posix(), STOP_CHECK_FLAG)


def claude_entry() -> dict[str, Any]:
    """Claude Code's PreToolUse entry: no matcher, so every tool."""
    return hook_entry(command("claude_code"))


def cursor_entries() -> dict[str, list[dict[str, Any]]]:
    """Cursor's entry under its generic pre-tool event, fail-closed like every gate there."""
    return {vendors.pre_tool_event("cursor"): [cursor_entry(command("cursor"), fail_closed=True)]}


def generic_doc(vendor: str) -> Any:
    """`vendor`'s pre-tool hook-config document running the stop check, agentseam's rendering, no matcher."""
    return generic_pre_tool_config(vendor, command(vendor), None)


def copilot_entries(vendor: str) -> dict[str, list[dict[str, Any]]]:
    """chock's own Copilot hooks file's stop-check entry, under its pre-tool event."""
    return {vendors.pre_tool_event(vendor): [copilot_entry(command(vendor))]}


def plugin_doc(agent: str, hooks: Any, *, generic: bool) -> Any:
    """A plugin's stop-check document: the runtime its own hooks already run, `--stop-check`, no matcher.

    `generic` for a package in the vendor's own agentseam dialect (the hook-folder stores); otherwise the
    hooks-map dialect the package's gate speaks, fail-closed where the vendor's entry is flat (Cursor).
    """
    found = heartbeat.plugin_runtime(agent, hooks)
    if not found:
        msg = f"no hook in this {agent} plugin runs its runtime, so it cannot carry the stop check"
        raise ValueError(msg)
    stop = f"{found} {STOP_CHECK_FLAG}"
    if generic:
        return generic_pre_tool_config(agent, stop, None)
    entries = {
        vendors.pre_tool_event(agent): [
            cursor_entry(stop, fail_closed=True) if vendors.hook_entry_flat(agent) else hook_entry(stop)
        ]
    }
    if vendors.hook_entry_flat(agent):
        return {**vendors.config_envelope(agent), "hooks": entries}
    return entries if vendors.hook_entry_bare(agent) else {"hooks": entries}


def _runs_it(node: Any) -> bool:
    return isinstance(node, dict) and isinstance(node.get("command"), str) and STOP_CHECK_FLAG in node["command"]


def without(node: Any) -> Any:
    """`node` with every stop-check entry gone, and any group or event list it leaves empty: a bundle wires its own once."""
    if isinstance(node, dict):
        out = {}
        for key, value in node.items():
            kept = without(value)
            if not (isinstance(value, list) and value and kept == []):
                out[key] = kept
            elif key == "hooks":
                return {}  # a group whose handlers were all stop checks goes whole, matcher and all
        return out
    if isinstance(node, list):
        kept = [(item, without(item)) for item in node if not _runs_it(item)]
        return [new for old, new in kept if not (old and new in ({}, []))]
    return node
