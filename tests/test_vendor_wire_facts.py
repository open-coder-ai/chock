"""C2 wire facts: what chock derives from agentseam, and the witnessed overrides it still records.

The derived-value tests freeze the wire bytes chock publishes: if an upstream vendor entry
changes, the derivation moves and these fail loudly instead of the bytes drifting silently.
The override tests bind each remaining chock-recorded fact to (a) its live witness evidence
and (b) the upstream value it disagrees with (derivation map M.5(4)/(5)): when agentseam
ingests the witnessed shape, they fail and say "delete the override and derive".
"""

from __future__ import annotations

import json

from agentseam import adapters
from agentseam.vendor_config import SCHEMA, VENDOR_CONFIG

from chock import evidence, vendors
from chock.compile.emitters import in_agent
from chock.hooks.in_agent_install import WIRED_VENDORS, agent_hooks_rel


def test_derived_wire_facts_still_produce_todays_bytes() -> None:
    """Mutating any of these upstream now moves chock's emitted bytes -- this is the alarm."""
    assert vendors.config_path("claude_code") == ".claude/settings.json"
    assert vendors.config_path("cursor") == ".cursor/hooks.json"
    assert str(agent_hooks_rel()) == ".github/hooks/chock.json"
    assert vendors.pre_tool_event("claude_code") == "PreToolUse"
    assert vendors.pre_tool_event("codex_cli") == "PreToolUse"
    assert vendors.pre_tool_event("vscode_copilot") == "PreToolUse"
    assert vendors.shell_gate_event("cursor") == "beforeShellExecution"
    assert vendors.config_envelope("cursor") == {"version": 1}
    assert vendors.config_envelope("claude_code") == {}
    assert in_agent.MATCHER == "Bash"


def test_every_wired_vendor_has_a_public_vendor_entry() -> None:
    for vendor in WIRED_VENDORS:
        assert vendor in VENDOR_CONFIG, f"{vendor} lost its agentseam vendor-config entry"


def test_shell_vocabulary_is_derived_per_vendor_not_borrowed() -> None:
    """codex_cli/vscode_copilot claude-format hooks used to borrow claude_code's matcher.

    agentseam now records a shell vocabulary for both, so in_agent.hooks_map_file must read
    each vendor's own tools.shell (vendors.shell_matcher) instead of falling back to
    claude_code's MATCHER; if a future release drops the vocabulary again, this fails and
    says to reinstate the borrow.
    """
    assert adapters.shell_tools("claude_code") == ("Bash",)
    for vendor in ("codex_cli", "vscode_copilot"):
        assert adapters.shell_tools(vendor), f"agentseam records no shell vocabulary for {vendor} anymore"

    vscode_matcher = vendors.shell_matcher("vscode_copilot")
    assert vscode_matcher != in_agent.MATCHER, (
        "vscode_copilot's own derived matcher happens to equal claude_code's -- "
        "pick a different vendor to prove derivation, not the borrowed constant"
    )
    (rendered_entry,) = in_agent.hooks_map_file("vscode_copilot", "CMD")["hooks"][
        vendors.pre_tool_event("vscode_copilot")
    ]
    assert rendered_entry["matcher"] == vscode_matcher, (
        "hooks_map_file still borrows claude_code's MATCHER instead of deriving vscode_copilot's own"
    )


def test_agent_hooks_shape_is_a_witnessed_override_until_upstream_ingests_it() -> None:
    """M.5(4): chock speaks `preToolUse` + bash/powershell/timeoutSec keys, witnessed live;

    agentseam 0.2.0 records `PreToolUse` + {type, command, windows}. The override may only
    exist while both halves hold: the witness row backs it, and upstream still disagrees.
    """
    assert evidence.witness("vscode_copilot", "agent-hooks") is not None, (
        "the agent-hooks witness row is gone; chock's override of agentseam's vscode_copilot "
        "wire facts has no evidence left -- re-witness or adopt the upstream shape"
    )
    upstream = VENDOR_CONFIG["vscode_copilot"]["wire_events"]["pre_tool"]
    assert in_agent.AGENT_HOOKS_EVENT == "preToolUse"
    assert upstream != in_agent.AGENT_HOOKS_EVENT, (
        "agentseam now records chock's witnessed event spelling: delete AGENT_HOOKS_EVENT "
        "and derive it from wire_events (derivation map M.5(4) is settled upstream)"
    )
    entry_extra = VENDOR_CONFIG["vscode_copilot"]["hook_entry"].get("entry_extra") or {}
    assert "bash" not in entry_extra and "timeoutSec" not in entry_extra, (
        "agentseam now records chock's witnessed entry keys: derive the agent-hooks entry "
        "shape from hook_entry instead of build_entry's hand-written keys"
    )


def test_repo_root_token_is_derived_from_vendor_config() -> None:
    """The `${CLAUDE_PROJECT_DIR}` wire token used to live in chock as a hardcoded copy.

    agentseam's vendor-config schema now carries `repo_root_token`; PROJECT_DIR_TOKEN must
    read it via vendors.repo_root_token instead. If a future release drops the field again,
    this fails and says to hardcode the token back.
    """
    assert "repo_root_token" in SCHEMA["properties"], "agentseam's vendor-config schema lost repo_root_token"
    assert VENDOR_CONFIG["claude_code"]["repo_root_token"] == "${CLAUDE_PROJECT_DIR}"
    assert vendors.repo_root_token("claude_code") == in_agent.PROJECT_DIR_TOKEN == "${CLAUDE_PROJECT_DIR}"


def test_cursor_fail_closed_stays_unset_pending_the_owner_decision() -> None:
    """M.5(5): setting failClosed is an enforcement-behaviour change (owner decision plus a

    witnessed run), never a silent flag-flip. chock's cursor wire bytes carry no failClosed;
    the flag's one source, when decided, is agentseam's public fail_closed accessor.
    """
    assert "failClosed" not in json.dumps(in_agent.cursor_hooks_file("CMD"))
    assert "failClosed" not in json.dumps(in_agent.cursor_entry("CMD"))
    rendered = adapters.get("cursor").hook_config(("pre_tool",), "CMD", fail_closed=True)
    (entry,) = rendered["hooks"]["preToolUse"]
    assert entry.get("failClosed") is True
    rendered = adapters.get("cursor").hook_config(("pre_tool",), "CMD", fail_closed=None)
    (entry,) = rendered["hooks"]["preToolUse"]
    assert "failClosed" not in entry


def test_home_level_config_vendors_stay_out_only_for_their_recorded_facts() -> None:
    """junie/kimi_code block per the matrix but are excluded from the in-agent set for one

    reason each chock can read upstream: a home-anchored config path (both), a TOML config
    (kimi_code). The day upstream records a repo-level JSON config, membership widens by
    derivation alone -- extend wiring, goldens and docs then, not this exclusion.
    """
    from chock.vendors import in_agent_vendors, repo_wirable

    assert str(VENDOR_CONFIG["junie"]["config_path"]).startswith("~")
    assert str(VENDOR_CONFIG["kimi_code"]["config_path"]).startswith("~")
    assert VENDOR_CONFIG["kimi_code"]["config_format"] == "toml"
    for vendor in ("junie", "kimi_code"):
        assert not repo_wirable(vendor)
        assert vendor not in in_agent_vendors()


def test_the_derived_vendor_set_is_the_predicate_recomputed() -> None:
    """Design test (a) at the vendor level: membership is can_block x repo-wirable, recomputed."""
    from agentseam import contract as _contract
    from agentseam import matrix as _matrix

    from chock.vendors import in_agent_vendors, repo_wirable

    recomputed = {
        vendor for vendor in VENDOR_CONFIG if _matrix.can_block(vendor, _contract.PRE_TOOL) and repo_wirable(vendor)
    }
    assert set(in_agent_vendors()) == recomputed
    assert "junie" in VENDOR_CONFIG and "kimi_code" in VENDOR_CONFIG
