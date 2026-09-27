"""INDEX.md says where a gate runs.

The heading once said gates are enforced "at commit/push", and an agent reading it could fairly
expect nothing until then -- while a gate compiled for tool use refuses its write in the turn.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from chock.index.builder import build_entries
from chock.index.render import GATES_HEADING, IN_AGENT_NOTE, render_index


def _gate(tmp_path: Path, policy_id: str, on: list[str]) -> None:
    dir_ = tmp_path / ".agents" / "policies" / policy_id
    dir_.mkdir(parents=True)
    manifest = {
        "id": policy_id,
        "name": policy_id,
        "version": "0.1.0",
        "description": f"Description for {policy_id}.",
        "artifact": "hook",
        "enforcement": "block",
        "provenance": {"author": "x", "license": "Apache-2.0", "trust_tier": "sandbox"},
        "hook": {"gate": {"kind": "content_regex", "on": on, "message": f"{policy_id} refused.", "params": {}}},
    }
    (dir_ / "manifest.yaml").write_text(yaml.safe_dump(manifest), encoding="utf-8")


def _line(index: str, policy_id: str) -> str:
    return next(line for line in index.splitlines() if line.startswith(f"- **{policy_id}**"))


def test_a_gate_compiled_for_tool_use_is_marked_as_checked_in_the_agent(tmp_path: Path) -> None:
    _gate(tmp_path, "in-agent", ["commit", "tool_use"])
    _gate(tmp_path, "commit-only", ["commit"])
    entries, _ = build_entries(tmp_path)
    index = render_index(entries, 2000).main
    assert GATES_HEADING in index
    assert "in the agent" in GATES_HEADING
    assert _line(index, "in-agent").endswith(IN_AGENT_NOTE)
    assert IN_AGENT_NOTE not in _line(index, "commit-only")
