"""The hook-config documents an in-agent surface installs: one entry shape, per vendor dialect."""

from __future__ import annotations

import json
from typing import Any

from chock import vendors
from chock.gate.budget import ENGINE_BUDGET_SECONDS
from chock.resources import package_data_dir

#: Interpreter start-up the engine's own timers do not cover; the client's timeout must outlast it.
STARTUP_MARGIN_SECONDS = 15
#: A client hook timeout fails OPEN, so it must fire after the engine's own (ask-a-person) timers.
TIMEOUT_SECONDS = ENGINE_BUDGET_SECONDS + STARTUP_MARGIN_SECONDS

_MS_PER_SECOND = 1000
#: The hooks-schema timeout field and unit of each generic vendor, with the doc it was read from.
VENDOR_TIMEOUTS: dict[str, dict[str, Any]] = json.loads(
    package_data_dir("chock", "data").joinpath("hook_timeouts.json").read_text(encoding="utf-8")
)
#: Vendors whose documented hook schema has no timeout field: the client's own, undocumented default applies.
NO_TIMEOUT_KEY_VENDORS = frozenset(v for v, facts in VENDOR_TIMEOUTS.items() if facts["field"] is None)

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


def vendor_timeout(vendor: str) -> tuple[str, int] | None:
    """(field, value in the vendor's own unit) of the timeout `vendor`'s hook schema documents, else None."""
    facts = VENDOR_TIMEOUTS.get(vendor)
    if facts is None or facts["field"] is None:
        return None
    return facts["field"], TIMEOUT_SECONDS * (_MS_PER_SECOND if facts["unit"] == "ms" else 1)


def with_timeout(vendor: str, doc: dict[str, Any]) -> dict[str, Any]:
    """`doc` (agentseam's rendering) with `vendor`'s timeout on every hook entry; unchanged where it has no key."""
    timeout = vendor_timeout(vendor)
    if timeout is not None:
        field, value = timeout
        _stamp(doc, field, value)
    return doc


def _stamp(node: Any, field: str, value: int) -> None:
    """Set `field` on every hook entry under `node`: each dict carrying a `command` string."""
    if isinstance(node, dict):
        if isinstance(node.get("command"), str):
            node[field] = value
        for child in node.values():
            _stamp(child, field, value)
    elif isinstance(node, list):
        for child in node:
            _stamp(child, field, value)


def generic_hooks_file(vendor: str, command: str) -> dict[str, Any]:
    """`vendor`'s full hook-config document for one guard command, agentseam's rendering plus its timeout.

    Paths inside `command` are repo-relative and resolve wherever the session started: the
    launcher form has git run them from the repository's top level.
    """
    return generic_pre_tool_config(vendor, command, vendors.shell_matcher(vendor))


def generic_pre_tool_config(vendor: str, command: str, matcher: str | None) -> dict[str, Any]:
    """The vendor's pre-tool hook-config document running `command`, with its timeout."""
    return with_timeout(vendor, vendors.pre_tool_hook_config(vendor, command, matcher=matcher))


def generic_stop_config(vendor: str, command: str) -> dict[str, Any]:
    """The vendor's turn-end hook-config document running `command`, with its timeout."""
    return with_timeout(vendor, vendors.stop_hook_config(vendor, command))


def generic_post_tool_config(vendor: str, command: str) -> dict[str, Any]:
    """The vendor's after-tool hook-config document running `command`, with its timeout."""
    return with_timeout(vendor, vendors.post_tool_hook_config(vendor, command))


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
