"""E-ALL: `chock sync` reaches every agentseam adapter whose hook config sits in the repository."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from agentseam import tier_table
from agentseam.vendor_config import VENDOR_CONFIG
from conftest import baseline_policy, init_repo

from chock import evidence, vendors
from chock.hooks import sync_notes
from chock.hooks.in_agent_install import WIRED_VENDORS, installed_policy_ids
from chock.hooks.in_agent_toml import OWNER
from chock.hooks.runtime_vendor import runtime_rel
from chock.scaffold.recompile import HookWiringError, recompile

#: The agents E-ALL added, by chock agent name. Each answers in its own grammar (tests/test_guard_fail_to_ask.py).
NEW = {"factory-droid": "factory_droid", "goose": "goose", "openhands": "openhands", "mistral-vibe": "mistral_vibe"}
#: Adapters sync does not wire yet, and why: a hooks directory runs one command per event, and a
#: home-anchored config is outside the repository. A new upstream adapter lands in one list or the other.
NOT_WIRED = {"cline": "hook_dir", "junie": "home", "kimi_code": "home"}
POLICIES = ("block-destructive-commands", "block-invisible-unicode")


def _repo(tmp_path: Path) -> Path:
    repo = init_repo(tmp_path)
    for policy in POLICIES:
        shutil.copytree(baseline_policy(policy), repo / ".agents" / "policies" / policy)
    return repo


def _tree(repo: Path) -> dict[str, bytes]:
    return {
        p.relative_to(repo).as_posix(): p.read_bytes()
        for p in repo.rglob("*")
        if p.is_file() and ".git" not in p.relative_to(repo).parts
    }


def test_every_adapter_is_a_selectable_agent() -> None:
    assert set(VENDOR_CONFIG) <= set(vendors.CHOCK_AGENT.values())
    for name, vendor in NEW.items():
        assert vendors.CHOCK_AGENT[name] == vendor


def test_every_adapter_is_wired_or_named_here_with_its_reason() -> None:
    unwired = {v for v in VENDOR_CONFIG if v not in WIRED_VENDORS}
    assert unwired == set(NOT_WIRED)
    for vendor, reason in NOT_WIRED.items():
        home = str(VENDOR_CONFIG[vendor]["config_path"]).startswith("~")
        assert (reason == "home") == home
        assert (reason == "hook_dir") == (vendors.config_format(vendor) == "hook_dir")


@pytest.mark.parametrize("name", sorted(NEW))
def test_sync_writes_the_vendors_documented_hook_file(name: str, tmp_path: Path) -> None:
    vendor = NEW[name]
    repo = _repo(tmp_path)
    recompile(repo, [name], skip_hooks=False)

    config = repo / vendors.config_path(vendor)
    assert config.is_file()
    assert (repo / runtime_rel(vendor)).is_file()
    assert runtime_rel(vendor).as_posix() in config.read_text(encoding="utf-8")
    assert set(POLICIES) <= installed_policy_ids(repo, vendor)


def test_goose_gets_chocks_own_plugin_directory() -> None:
    assert vendors.config_path("goose") == ".agents/plugins/chock/hooks/hooks.json"


@pytest.mark.parametrize("name", sorted(NEW))
def test_a_second_sync_changes_nothing(name: str, tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    recompile(repo, [name], skip_hooks=False)
    before = _tree(repo)

    recompile(repo, [name], skip_hooks=False)

    assert _tree(repo) == before


def _foreign_json(vendor: str) -> dict:
    """A hook entry chock does not own, in the vendor's own document shape."""
    return vendors.pre_tool_hook_config(vendor, "./their-own-hook.sh", "Shell")


@pytest.mark.parametrize("name", sorted(n for n, v in NEW.items() if vendors.config_format(v) == "json"))
def test_a_strangers_json_entry_survives_sync_and_deselect(name: str, tmp_path: Path) -> None:
    vendor = NEW[name]
    repo = _repo(tmp_path)
    config = repo / vendors.config_path(vendor)
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(json.dumps(_foreign_json(vendor)), encoding="utf-8")

    recompile(repo, [name], skip_hooks=False)
    assert "./their-own-hook.sh" in config.read_text(encoding="utf-8")

    recompile(repo, ["claude"], skip_hooks=False)
    assert json.loads(config.read_text(encoding="utf-8")) == _foreign_json(vendor)
    assert not (repo / runtime_rel(vendor)).exists()


FOREIGN_RULE = '[[hooks]]\nname = "theirs"\ntype = "pre_tool"\ncommand = "./their-own-hook.sh"\n'


def test_vibe_rules_are_one_owned_block_beside_a_strangers_rule(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    config = repo / vendors.config_path("mistral_vibe")
    config.parent.mkdir(parents=True)
    config.write_text(FOREIGN_RULE, encoding="utf-8")

    recompile(repo, ["mistral-vibe"], skip_hooks=False)
    text = config.read_text(encoding="utf-8")
    assert text.startswith(FOREIGN_RULE)
    assert text.count(f">>> agentseam >>> {OWNER}") == 1
    assert "timeout = 45" in text, "the vendor's documented timeout field carries chock's budget"

    recompile(repo, ["claude"], skip_hooks=False)
    assert config.read_text(encoding="utf-8") == FOREIGN_RULE


def test_vibe_file_chock_alone_wrote_is_removed_on_deselect(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    recompile(repo, ["mistral-vibe"], skip_hooks=False)
    config = repo / vendors.config_path("mistral_vibe")
    assert config.is_file()

    recompile(repo, ["claude"], skip_hooks=False)

    assert not config.exists()
    assert not (repo / runtime_rel("mistral_vibe")).exists()


def test_vibe_refuses_a_file_it_cannot_read(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    config = repo / vendors.config_path("mistral_vibe")
    config.parent.mkdir(parents=True)
    config.write_bytes(b"\xff\xfe not text")

    with pytest.raises(HookWiringError, match="not readable text"):
        recompile(repo, ["mistral-vibe"], skip_hooks=False)

    assert config.read_bytes() == b"\xff\xfe not text"


@pytest.mark.parametrize("vendor", sorted(NEW.values()))
def test_sync_says_agentseams_row_and_that_the_agent_is_untested(vendor: str) -> None:
    row = next(r for r in tier_table.rows() if r["agent"] == vendor)
    lines = sync_notes.notes(vendor)

    assert any(row["basis"] in line and row["grade"] in line and row["recorded"] in line for line in lines)
    assert any("Untested" in line for line in lines)


@pytest.mark.parametrize("vendor", ("vscode_copilot", "claude_code", "cursor"))
def test_a_witnessed_agent_is_not_called_untested(vendor: str) -> None:
    assert evidence.witness(vendor, "agent-hooks"), "the ledger's repo-hook row this test rests on"
    assert sync_notes.witnessed(vendor)
    assert not any("Untested" in line for line in sync_notes.notes(vendor))


@pytest.mark.parametrize("vendor", ("codex_cli", "devin"))
def test_a_plugin_witness_does_not_make_sync_say_tested(vendor: str) -> None:
    """A plugin-hook row witnesses `chock install`; sync wires repo hooks nobody saw run there."""
    assert evidence.witness(vendor, evidence.PLUGIN_HOOK)
    assert not sync_notes.witnessed(vendor)
    assert any("Untested" in line for line in sync_notes.notes(vendor))


def test_a_repo_hook_row_is_what_sync_reads() -> None:
    row = evidence.Witness("claude_code", "pre-tool-use", "a real client", "2026-10-12", "live probe")
    assert sync_notes.witnessed("claude_code", ledger=(row,))
    assert not sync_notes.witnessed("claude_code", ledger=(row._replace(surface=evidence.PLUGIN_HOOK),))
