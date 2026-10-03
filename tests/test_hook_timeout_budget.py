"""A client hook timeout fails OPEN, so it must outlast the engine's own ask-a-person timer."""

from __future__ import annotations

import pytest

from chock.compile.emitters import in_agent, in_agent_hooks
from chock.gate import guard_runner

ENGINE_BUDGET = guard_runner._GUARD_TIMEOUT_SECONDS
HOOK_VENDORS = ["claude_code", "codex_cli", "devin", "vscode_copilot"]


def test_margin_covers_interpreter_startup() -> None:
    assert in_agent_hooks.TIMEOUT_SECONDS == ENGINE_BUDGET + in_agent_hooks.STARTUP_MARGIN_SECONDS
    assert in_agent_hooks.STARTUP_MARGIN_SECONDS > 0


@pytest.mark.parametrize("vendor", HOOK_VENDORS)
def test_hooks_map_timeout_exceeds_engine_budget(vendor: str) -> None:
    doc = in_agent_hooks.hooks_map_file(vendor, "cmd")
    events = doc.get("hooks", doc)
    timeouts = [h["timeout"] for entries in events.values() for e in entries for h in e.get("hooks", [e])]
    assert timeouts
    assert all(t > ENGINE_BUDGET for t in timeouts)


def test_cursor_timeout_exceeds_engine_budget() -> None:
    assert in_agent_hooks.cursor_entry("cmd")["timeout"] > ENGINE_BUDGET


def test_copilot_timeouts_exceed_engine_budget() -> None:
    entry = in_agent.copilot_entry("cmd")
    assert entry["timeout"] > ENGINE_BUDGET
    assert entry["timeoutSec"] > ENGINE_BUDGET
