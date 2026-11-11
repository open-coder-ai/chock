"""INDEX.md says where a gate runs.

The heading once said gates are enforced "at commit/push", and an agent reading it could fairly
expect nothing until then -- while a gate compiled for tool use refuses its write in the turn.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from chock.compile.compiler import compile_policy
from chock.config import load_config, policy_status
from chock.index.builder import build_entries
from chock.index.render import GATES_HEADING, IN_AGENT_NOTE, render_index


def _gate(tmp_path: Path, policy_id: str, on: list[str], params: dict | None = None) -> None:
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
        "hook": {
            "gate": {"kind": "content_regex", "on": on, "message": f"{policy_id} refused.", "params": params or {}}
        },
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


_IN_AGENT_SURFACES = {"pre-tool-use", "stop", "agent-hooks"}


def _override_surfaces(tmp_path: Path, policy_id: str, surfaces: list[str]) -> None:
    config = {"policies": {"overrides": {policy_id: {"surfaces": surfaces}}}}
    (tmp_path / ".chock").mkdir(exist_ok=True)
    (tmp_path / ".chock" / "config.yaml").write_text(yaml.safe_dump(config), encoding="utf-8")


def _compiled_surfaces(tmp_path: Path, policy_id: str) -> set[str]:
    """The surfaces `chock sync` compiles for the policy: the manifest under this repo's config."""
    policy_dir = tmp_path / ".agents" / "policies" / policy_id
    manifest = yaml.safe_load((policy_dir / "manifest.yaml").read_text(encoding="utf-8"))
    targets = policy_status(load_config(tmp_path), policy_id, manifest)["targets"]
    result = compile_policy(
        policy_dir, targets=targets, output_root=tmp_path / ".chock" / "compiled", repo_root=tmp_path
    )
    return {surface for surface, paths in result.artifacts.items() if paths}


def test_a_surfaces_override_without_the_agent_drops_the_in_agent_note(tmp_path: Path) -> None:
    _gate(tmp_path, "block-marker", ["commit", "tool_use"], {"content_pattern": "DO-NOT-COMMIT"})
    assert _compiled_surfaces(tmp_path, "block-marker") & _IN_AGENT_SURFACES
    _override_surfaces(tmp_path, "block-marker", ["git-hook", "ci-gate"])
    assert _compiled_surfaces(tmp_path, "block-marker") == {"git-hook", "ci-gate"}
    entries, _ = build_entries(tmp_path)
    assert IN_AGENT_NOTE not in _line(render_index(entries, 2000).main, "block-marker")


def test_a_surfaces_override_that_keeps_an_agent_surface_keeps_the_note(tmp_path: Path) -> None:
    _gate(tmp_path, "block-marker", ["commit", "tool_use"], {"content_pattern": "DO-NOT-COMMIT"})
    _override_surfaces(tmp_path, "block-marker", ["git-hook", "stop"])
    assert _compiled_surfaces(tmp_path, "block-marker") & _IN_AGENT_SURFACES
    entries, _ = build_entries(tmp_path)
    assert _line(render_index(entries, 2000).main, "block-marker").endswith(IN_AGENT_NOTE)


def test_an_override_to_advise_drops_the_in_agent_note(tmp_path: Path) -> None:
    _gate(tmp_path, "block-marker", ["commit", "tool_use"], {"content_pattern": "DO-NOT-COMMIT"})
    config = {"policies": {"overrides": {"block-marker": {"enforcement": "advise"}}}}
    (tmp_path / ".chock").mkdir()
    (tmp_path / ".chock" / "config.yaml").write_text(yaml.safe_dump(config), encoding="utf-8")
    assert not _compiled_surfaces(tmp_path, "block-marker") & _IN_AGENT_SURFACES
    entries, _ = build_entries(tmp_path)
    assert IN_AGENT_NOTE not in _line(render_index(entries, 2000).main, "block-marker")
