"""One hook entry per (event, matcher): every vendor's config carries a pinned policy index, never one entry per policy."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from pathlib import Path

import pytest
from conftest import baseline_policy

from chock import vendors
from chock.compile.emitters.in_agent_hooks import generic_pre_tool_config
from chock.hooks import multi_wiring
from chock.hooks.in_agent_install import WIRED_VENDORS, install_hooks, installed_policy_ids, uninstall_hooks
from chock.hooks.multi_wiring import INDEX_DIR, INDEX_SHA_FLAG, MULTI_FLAG, IndexRefusalError
from chock.hooks.wiring_drift import wiring_differences
from chock.scaffold.recompile import recompile

GUARDS = ("block-destructive-commands", "block-no-verify", "protect-commit-privacy")
#: windsurf's hook schema has no timeout field and no documented default: no member can be shown to fit, so it keeps one entry per policy.
UNBOUNDED = ("windsurf",)
FOLDED = tuple(v for v in WIRED_VENDORS if v not in UNBOUNDED)
PIN = re.compile(rf"{MULTI_FLAG} \\?\"?(?P<rel>[^\s\"\\]+)\\?\"? {INDEX_SHA_FLAG} (?P<pin>[0-9a-f]{{64}})")


@pytest.fixture(scope="module")
def wired(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Three shell guards compiled for every vendor and installed into each vendor's config."""
    root = tmp_path_factory.mktemp("wired")
    for policy in GUARDS:
        shutil.copytree(baseline_policy(policy), root / ".agents" / "policies" / policy)
    recompile(root, ["claude"])
    for vendor in WIRED_VENDORS:
        install_hooks(root, vendor)
    return root


def _config_text(root: Path, vendor: str) -> str:
    path = root / (".github/hooks/chock.json" if vendor == "vscode_copilot" else vendors.config_path(vendor))
    return path.read_text(encoding="utf-8")


def _indexes(root: Path, vendor: str) -> list[Path]:
    return sorted((root / INDEX_DIR).glob(f"{vendor}-*.json"))


@pytest.mark.parametrize("vendor", FOLDED)
def test_the_guards_share_one_entry_whose_pin_is_the_hash_of_the_index(wired: Path, vendor: str) -> None:
    text = _config_text(wired, vendor)
    pinned = {m["pin"]: m["rel"] for m in PIN.finditer(text)}
    assert pinned, f"{vendor}: no pinned index"
    members = []
    for pin, rel in pinned.items():
        body = (wired / rel).read_bytes()
        assert hashlib.sha256(body).hexdigest() == pin
        members += [tuple(m["argv"]) for m in json.loads(body)["members"]]
    assert {Path(argv[1]).parts[2] for argv in members} == set(GUARDS)
    assert len(pinned) == 1, f"{vendor}: the guards sit in {len(pinned)} indexes, not one"
    assert "--guard" not in text, f"{vendor}: a per-policy guard entry is left"


def test_every_member_carries_the_timeout_its_policy_runs_under_today(wired: Path) -> None:
    """Today every policy's entry carries TIMEOUT_SECONDS (the 30 s engine budget + the start-up margin), so every member is 30 s."""
    from chock.compile.emitters.in_agent_hooks import STARTUP_MARGIN_SECONDS, TIMEOUT_SECONDS
    from chock.gate.budget import ENGINE_BUDGET_SECONDS

    for policy in GUARDS:
        compiled = json.loads((wired / ".chock/compiled" / policy / "pre-tool-use/pretooluse.json").read_text("utf-8"))
        assert {h["timeout"] for h in compiled["hooks"]} == {TIMEOUT_SECONDS}
    seen = [
        m["timeout"]
        for v in FOLDED
        for i in _indexes(wired, v)
        for m in _members(wired, i.relative_to(wired).as_posix())
    ]
    assert seen
    assert set(seen) == {ENGINE_BUDGET_SECONDS} == {TIMEOUT_SECONDS - STARTUP_MARGIN_SECONDS}


def test_a_vendor_whose_timeout_is_unknown_keeps_one_entry_per_policy(wired: Path) -> None:
    text = _config_text(wired, "windsurf")
    assert text.count("--guard") >= len(GUARDS)
    assert MULTI_FLAG not in text


def _members(root: Path, rel: str) -> list[dict]:
    return json.loads((root / rel).read_text(encoding="utf-8"))["members"]


@pytest.mark.parametrize("vendor", WIRED_VENDORS)
def test_every_wired_policy_counts_as_installed(wired: Path, vendor: str) -> None:
    assert set(GUARDS) <= installed_policy_ids(wired, vendor)


@pytest.mark.parametrize("vendor", [v for v in FOLDED if vendors.config_format(v) != "toml"])
def test_agentseam_renders_a_pinned_command_unchanged_for_the_vendor(wired: Path, vendor: str) -> None:
    """The vendor's own renderer is handed the folded command and writes it back whole, in every field that carries it."""
    command = next(c for c in _commands(json.loads(_config_text(wired, vendor))) if MULTI_FLAG in c)
    rendered = generic_pre_tool_config(vendor, command, vendors.shell_matcher(vendor))
    assert command in _commands(rendered)
    assert all(MULTI_FLAG in c for c in _commands(rendered))


def _commands(node: object) -> list[str]:
    if isinstance(node, dict):
        return [v for k, v in node.items() if k == "command" and isinstance(v, str)] + [
            c for v in node.values() for c in _commands(v)
        ]
    return [c for v in node for c in _commands(v)] if isinstance(node, list) else []


def test_an_old_per_policy_config_is_drift_and_syncing_it_clears_the_drift(wired: Path, tmp_path: Path) -> None:
    root = tmp_path / "old"
    shutil.copytree(wired, root)
    config = root / vendors.config_path("claude_code")
    doc = json.loads(config.read_text(encoding="utf-8"))
    first = next(e for e in doc["hooks"]["PreToolUse"] if MULTI_FLAG in e["hooks"][0]["command"])
    members = _members(root, PIN.search(first["hooks"][0]["command"])["rel"])
    old = [json.loads(json.dumps(first)) for _ in members]
    for entry, member in zip(old, members, strict=True):
        head = first["hooks"][0]["command"].split(f" {MULTI_FLAG}")[0]
        entry["hooks"][0]["command"] = f'{head} {member["argv"][0]} "{member["argv"][1]}"'
    doc["hooks"]["PreToolUse"] = [*old, *(e for e in doc["hooks"]["PreToolUse"] if e is not first)]
    config.write_text(json.dumps(doc), encoding="utf-8")

    assert f"differs: {vendors.config_path('claude_code')}" in wiring_differences(root, ("claude_code",))
    install_hooks(root, "claude_code")
    assert not wiring_differences(root, ("claude_code",))


def test_a_member_file_edited_after_sync_is_index_drift(wired: Path, tmp_path: Path) -> None:
    root = tmp_path / "edited"
    shutil.copytree(wired, root)
    guard = root / ".agents" / "policies" / GUARDS[1] / "implementations" / f"{GUARDS[1]}.py"
    guard.write_text(guard.read_text(encoding="utf-8") + "\n# edited\n", encoding="utf-8")
    assert any(
        d.startswith(f"differs: {INDEX_DIR.as_posix()}/claude_code-")
        for d in wiring_differences(root, ("claude_code",))
    )


def test_uninstalling_a_vendor_removes_its_indexes(wired: Path, tmp_path: Path) -> None:
    root = tmp_path / "gone"
    shutil.copytree(wired, root)
    assert _indexes(root, "claude_code")
    uninstall_hooks(root, "claude_code")
    assert not _indexes(root, "claude_code")


def test_a_member_that_cannot_finish_inside_the_entry_timeout_is_refused(
    wired: Path, tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path / "slow"
    shutil.copytree(wired, root)
    monkeypatch.setattr(multi_wiring, "MEMBER_SECONDS", 44)
    with pytest.raises(IndexRefusalError, match="timeout"):
        install_hooks(root, "claude_code")


def test_an_entry_naming_no_file_chock_can_place_stays_a_single_policy_entry(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    entry = {
        "matcher": "Bash",
        "hooks": [{"type": "command", "command": "x .chock/bin/claude_code.py --guard ghost.py", "timeout": 45}],
    }
    assert multi_wiring.collapse_list(tmp_path, "claude_code", "PreToolUse", [entry], set()) == [entry]
