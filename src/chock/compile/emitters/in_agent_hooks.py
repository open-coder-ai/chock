"""The hook-config documents an in-agent surface installs: one entry shape, per vendor dialect."""

from __future__ import annotations

from typing import Any

from chock import vendors
from chock.gate import guard_runner

#: Interpreter start-up the guard's own timer does not cover; the client's timeout must outlast it.
STARTUP_MARGIN_SECONDS = 15
#: A client hook timeout fails OPEN, so it must fire after the guard's own (ask-a-person) timer.
TIMEOUT_SECONDS = guard_runner._GUARD_TIMEOUT_SECONDS + STARTUP_MARGIN_SECONDS

#: `exit $LASTEXITCODE` alone exits 0 when no native command ran (git or sh not on PATH):
#: $LASTEXITCODE is $null then, and 0 is an allow; nothing judged the call, so refuse (2).
POWERSHELL_KEEP_EXIT = "; if ($null -eq $LASTEXITCODE) { exit 2 }; exit $LASTEXITCODE"


def adapter_rel(vendor: str) -> str:
    """Where the vendored runtime lives in a consumer repo: chock's convention + agent id."""
    return f".chock/bin/{vendor}.py"


def copilot_entry(bash: str, *, matcher: str | None = None) -> dict[str, Any]:
    """One entry of chock's own Copilot hooks file: witnessed keys, both shells' spellings.

    The launcher form reads the same under bash and PowerShell; PowerShell also needs its exit
    code kept (`pwsh -Command` reports any failure as 1), as agentseam's own Windows form does.
    """
    powershell = f"& {bash}{POWERSHELL_KEEP_EXIT}"
    entry: dict[str, Any] = {"type": "command"}
    if matcher is not None:
        entry["matcher"] = matcher
    entry.update(
        {
            "timeout": TIMEOUT_SECONDS,
            "timeoutSec": TIMEOUT_SECONDS,
            "bash": bash,
            "command": bash,
            "powershell": powershell,
            "windows": powershell,
        }
    )
    return entry


def generic_hooks_file(vendor: str, command: str) -> dict[str, Any]:
    """`vendor`'s full hook-config document for one guard command, agentseam's rendering.

    Paths inside `command` are repo-relative and resolve wherever the session started: the
    launcher form has git run them from the repository's top level.
    """
    return vendors.pre_tool_hook_config(vendor, command, matcher=vendors.shell_matcher(vendor))


def hook_entry(command: str, *, matcher: str | None = None) -> dict[str, Any]:
    """One hooks-map entry (agentseam's `hooks_map` wrapper shape) plus chock's timeout."""
    entry: dict[str, Any] = {}
    if matcher is not None:
        entry["matcher"] = matcher
    entry["hooks"] = [{"type": "command", "command": command, "timeout": TIMEOUT_SECONDS}]
    return entry


def hooks_map_file(vendor: str, command: str) -> dict[str, Any]:
    """A hooks file under `vendor`'s own pre-tool event spelling.

    Wrapped in a top-level `hooks` key (the claude-plugin format) unless `vendor`'s own
    hook_entry is bare -- Devin's native `hooks.json` at the plugin root is the event map
    itself, with no wrapper, unlike the nested `hooks/hooks.json` every other format here
    shares.
    """
    matcher = vendors.shell_matcher(vendor)
    event_map = {vendors.pre_tool_event(vendor): [hook_entry(command, matcher=matcher)]}
    return event_map if vendors.hook_entry_bare(vendor) else {"hooks": event_map}


def cursor_entry(command: str, *, fail_closed: bool = False) -> dict[str, Any]:
    """One cursor hook entry: the flat `cursor` wrapper shape plus chock's timeout.

    `fail_closed` for a gate that must refuse: Cursor otherwise allows when the hook crashes,
    times out or cannot start (docs: cursor.com/docs/agent/hooks, `failClosed`).
    """
    entry: dict[str, Any] = {"command": command, "timeout": TIMEOUT_SECONDS}
    if fail_closed:
        entry["failClosed"] = True
    return entry


def cursor_hooks_file(command: str) -> dict[str, Any]:
    """A cursor-format hooks file: envelope and shell-gate event, fail-closed, from the vendor entry."""
    return {
        **vendors.config_envelope("cursor"),
        "hooks": {vendors.shell_gate_event("cursor"): [cursor_entry(command, fail_closed=True)]},
    }
