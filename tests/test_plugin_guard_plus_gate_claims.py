"""What the published claims say about a package carrying a guard and a gate: never one half's word alone."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from bundle_fixtures import write
from guard_gate_support import BUILDERS, POLICY_ID, make_policy

from chock.plugin import bundle_grade, catalog_page
from chock.plugin.bundle_build import Member, merged_files


def _bundle() -> dict:
    return {"id": "guarded-set", "version": "0.1.0", "description": "One guarded set.", "members": [POLICY_ID]}


@pytest.mark.parametrize(
    ("client", "manifest_rel"), [("codex", ".codex-plugin/plugin.json"), ("copilot", "plugin.json")]
)
def test_a_merged_bundle_carries_and_states_both_halves(tmp_path: Path, client: str, manifest_rel: str) -> None:
    pack, data = make_policy(tmp_path, guard=True, gate=True)
    members = [Member(pack, data)]
    files = merged_files(client, _bundle(), members, tmp_path)
    hooks = next(json.loads(text) for rel, text in files.items() if rel.name == "hooks.json")
    commands = bundle_grade._hook_commands(hooks)
    assert any("--guard" in c for c in commands) and any("--gate" in c for c in commands)
    description = json.loads(files[Path(manifest_rel)])["description"]
    assert "Shell guard:" in description and "Write gate:" in description
    assert "refuses a matched shell command before it runs; blocks" in description


def test_a_stop_only_gate_beside_a_guard_never_reads_as_judging_the_write(tmp_path: Path) -> None:
    """Copilot's guard sits at PreToolUse; that must not lend the Stop-only gate a write-path claim."""
    pack, data = make_policy(tmp_path, guard=True, gate=True)
    members = [Member(pack, data)]
    files = merged_files("copilot", _bundle(), members, tmp_path)
    description = json.loads(files[Path("plugin.json")])["description"]
    assert "at turn end only; the write itself is not judged" in description


def test_the_catalog_page_counts_each_half_and_says_some_ship_both(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    both, both_data = make_policy(tmp_path, guard=True, gate=True)
    BUILDERS["claude"](both, both_data, tmp_path, dist / "claude" / POLICY_ID)
    gate_only, gate_data = make_policy(tmp_path / "other", guard=False, gate=True, policy_id="gate-only")
    BUILDERS["claude"](gate_only, gate_data, tmp_path / "other", dist / "claude" / "gate-only")

    page = catalog_page.render_catalog_page(dist, "claude")
    assert "**2 policies are published here: 2 enforce in this client, 0 are advisory.**" in page
    assert "A guard package ships a guard script and a stdlib-only adapter, hooked at `PreToolUse`" in page
    assert "hooked at `PreToolUse` and `Stop`, judging the file a write would create" in page
    assert "1 of these packages ships both: the policy has a guard and a gate" in page


def test_the_catalog_page_is_unchanged_when_no_package_ships_both(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    pack, data = make_policy(tmp_path, guard=True, gate=False)
    BUILDERS["claude"](pack, data, tmp_path, dist / "claude" / POLICY_ID)
    page = catalog_page.render_catalog_page(dist, "claude")
    assert "ships both" not in page and "A gate package" not in page


def test_a_package_wiring_no_known_command_counts_as_neither_half(tmp_path: Path) -> None:
    hooks = tmp_path / "hooks.json"
    write(tmp_path, {Path("hooks.json"): json.dumps({"hooks": {"PreToolUse": [{"command": "true"}]}})})
    assert catalog_page._package_kinds(hooks) == {}
    assert not bundle_grade.carries_guard(None)
    assert bundle_grade.events_for(["not", "a", "map"], "--gate") == []


def test_a_vendor_caveat_for_both_halves_is_stated_once_and_for_both(tmp_path: Path) -> None:
    from guard_gate_support import STORES

    pack, data = make_policy(tmp_path, guard=True, gate=True)
    codex_files = STORES["codex"][1](pack, data, tmp_path)
    codex_text = json.loads(codex_files[Path(".codex-plugin/plugin.json")])["description"]
    assert codex_text.count("one-time trust review") == 1
    copilot_files = STORES["copilot"][1](pack, data, tmp_path)
    copilot_text = json.loads(copilot_files[Path("plugin.json")])["description"]
    shared = copilot_text.split("Both halves:", 1)[1]
    assert "exports no plugin-root variable" in shared, "the root caveat covers the guard too"
    assert copilot_text.count("exports no plugin-root variable") == 1


def test_the_catalog_page_drops_instead_only_when_a_package_ships_both(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    both, both_data = make_policy(tmp_path, guard=True, gate=True)
    BUILDERS["claude"](both, both_data, tmp_path, dist / "claude" / POLICY_ID)
    assert "stdlib-only runner instead" not in catalog_page.render_catalog_page(dist, "claude")
    assert "stdlib-only runner instead" in catalog_page._explain("claude", (1, ["PreToolUse"]), (1, ["Stop"]))
