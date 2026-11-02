"""The bundled runtime's decode branches are replaced whole by chock's unreadable-payload refusal."""

from __future__ import annotations

import pytest
from agentseam import bundler

from chock.gate import runtime_bundle

AGENT = "claude_code"


def test_agentseam_still_emits_the_branch_chock_replaces():
    assert runtime_bundle._UNREADABLE_BRANCH in bundler.bundle(AGENT)


@pytest.mark.parametrize("agent", sorted(runtime_bundle.RUNTIME_AGENTS))
def test_rendered_runtime_has_chocks_refusal_and_none_of_the_decode_branches(agent):
    source = runtime_bundle.render(agent)
    assert runtime_bundle._UNREADABLE_REFUSAL in source
    assert runtime_bundle._UNREADABLE_BRANCH not in source
    assert "except json.JSONDecodeError:" not in source
    assert "except (ValueError, RecursionError, MemoryError):" not in source
