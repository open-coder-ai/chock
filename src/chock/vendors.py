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


#: Vendors chock wires through its OWN hooks file (.github/hooks/chock.json) instead of the
#: vendor's config, in an entry shape witnessed live rather than read from agentseam. That
#: witness covers the pre-tool key alone, so the file's turn-end spelling is unknown --
#: which is an install cap, like repo_wirable, not a claim about what the vendor can do.
AGENT_HOOKS_VENDORS = ("vscode_copilot",)


def in_agent_vendors() -> tuple[str, ...]:
    """Vendors the in-agent surface covers: the matrix blocking predicate, install-capped.

    Capability enters from `agentseam.matrix` only; the vendor entry contributes wire
    facts (and the install cap above), never capability.
    """
    return tuple(sorted(v for v in VENDOR_CONFIG if _matrix.can_block(v, _contract.PRE_TOOL) and repo_wirable(v)))


def stop_vendors() -> tuple[str, ...]:
    """Vendors the stop surface covers: the same predicate, asked about the turn-end event.

    A different set from `in_agent_vendors` in both directions, which is the point of
    deriving each one rather than inheriting: grok and windsurf can only observe a finished
    turn, while three vendors here can refuse one without recording any write vocabulary
    (cursor hands a refusal back as a follow-up message, witnessed live). vscode_copilot can refuse one too and is still held back -- see
    AGENT_HOOKS_VENDORS for the file chock would have to guess a key in.
    """
    return tuple(
        sorted(
            v
            for v in VENDOR_CONFIG
            if _matrix.can_block(v, _contract.STOP) and repo_wirable(v) and v not in AGENT_HOOKS_VENDORS
        )
    )


def config_path(vendor: str) -> str:
    """Repo-relative path of the file the vendor reads hook wiring from."""
    return str(entry(vendor)["config_path"])


def repo_root_token(vendor: str) -> str | None:
    """The vendor's own wire token for the repo root, or None where agentseam records none."""
    token = entry(vendor).get("repo_root_token")
    return str(token) if token else None


#: Said when agentseam records that the agent needs trust but gives no vendor-specific steps.
_TRUST_FALLBACK = "this agent runs a project's hooks only after you trust them in the agent itself"


def trust_hint(vendor: str) -> str | None:
    """How to make `vendor` run the repo's hooks, where it skips untrusted ones silently; else None."""
    cfg = entry(vendor)
    if not cfg.get("needs_trust"):
        return None
    return str(cfg.get("trust_hint") or _TRUST_FALLBACK)


def wire_event(vendor: str, canonical: str) -> str:
    """The vendor's wire spelling of one of agentseam's canonical events."""
    return str(_adapters.get(vendor).REVERSE_EVENT_MAP[canonical])


def pre_tool_event(vendor: str) -> str:
    """The vendor's wire spelling of the pre-tool gate event."""
    return wire_event(vendor, _contract.PRE_TOOL)


def stop_event(vendor: str) -> str:
    """The vendor's wire spelling of the end-of-turn event (`Stop`, `AfterAgent`, ...)."""
    return wire_event(vendor, _contract.STOP)


def shell_gate_event(vendor: str) -> str:
    """The wire event a shell-command gate registers under (cursor gates shell directly)."""
    verdicts = entry(vendor).get("verdicts") or {}
    return str(verdicts.get("default_wire_event") or pre_tool_event(vendor))


def shell_matcher(vendor: str) -> str | None:
    """Matcher over the vendor's recorded shell-tool vocabulary, or None where unrecorded."""
    tools = _adapters.shell_tools(vendor)
    return "|".join(tools) if tools else None


def write_tools(vendor: str) -> tuple[str, ...]:
    """The vendor's recorded file-writing tool vocabulary, empty where none is recorded.

    agentseam records `tools.shell` for most vendors and `tools.write` for few, so this is
    empty far more often than shell_tools is. Empty means unrecorded, never "no such tools":
    a matcher invented here would gate a tool name nobody verified the vendor uses.
    """
    config = getattr(_adapters.get(vendor), "CONFIG", None)
    tools = (config or {}).get("tools") if isinstance(config, dict) else None
    return tuple((tools or {}).get("write") or ())


def write_matcher(vendor: str) -> str | None:
    """Matcher over the vendor's recorded write-tool vocabulary, or None where unrecorded."""
    tools = write_tools(vendor)
    return "|".join(tools) if tools else None


def hook_entry_bare(vendor: str) -> bool:
    """Whether `vendor`'s own hook_config is the bare event map, with no top-level `hooks` key.

    Every vendor with a recorded `hook_entry` wraps its event map in `{"hooks": {...}}`,
    except Devin: its native `hooks.json` (unlike the nested `hooks/hooks.json` the Claude
    layout writes) is the bare map itself, confirmed by
    `agentseam.adapters.get("devin").CONFIG["hook_entry"] == {"bare": True, ...}`. A vendor
    with no recorded `hook_entry` (vscode_copilot, witnessed rather than derived) is not bare.
    """
    config = getattr(_adapters.get(vendor), "CONFIG", None)
    entry = (config or {}).get("hook_entry") if isinstance(config, dict) else None
    return bool((entry or {}).get("bare"))


def hook_entry_flat(vendor: str) -> bool:
    """Whether `vendor`'s hook entries are the flat `{"command": ...}` shape, with no matcher.

    Cursor's `hooks.json` lists each event's entries as bare command objects, recorded upstream
    as `CONFIG["hook_entry"] == {"matcher": False, "wrapper": "cursor"}`; every other vendor
    with a recorded entry nests the command under `hooks` and may carry a matcher.
    """
    config = getattr(_adapters.get(vendor), "CONFIG", None)
    entry = (config or {}).get("hook_entry") if isinstance(config, dict) else None
    return (entry or {}).get("wrapper") == "cursor"


def pre_tool_hook_config(vendor: str, command: str, matcher: str | None = None) -> dict[str, Any]:
    """The vendor's complete hook-config document gating pre-tool with `command`."""
    return _adapters.get(vendor).hook_config((_contract.PRE_TOOL,), command, matcher)


def stop_hook_config(vendor: str, command: str) -> dict[str, Any]:
    """The vendor's complete hook-config document running `command` when a turn ends.

    No matcher: the turn-end event carries no tool to match on, which is why this surface
    reaches every vendor the predicate admits rather than only the two that record a write
    vocabulary.
    """
    return _adapters.get(vendor).hook_config((_contract.STOP,), command, None)


def config_envelope(vendor: str) -> dict[str, Any]:
    """Wrapper keys the vendor's hook config carries beside its hooks table."""
    return {key: value for key, value in _adapters.get(vendor).hook_config((), "").items() if key != "hooks"}
