"""Devin packaging: native layout, root-level hooks.json, and the best-effort posture."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from conftest import guarded_launch

from chock.gate import runtime_bundle
from chock.plugin.cli import main as plugin_main
from chock.plugin.devin import (
    _BESTEFFORT_NOTE_DEVIN,
    POSTURE_BESTEFFORT_DEVIN,
    build_devin_plugin,
    devin_plugin_files,
)

GUARD_MANIFEST = {
    "id": "block-destructive-commands",
    "name": "Block Destructive Commands",
    "version": "0.0.1",
    "description": "Block rm -rf and friends before they run.",
    "artifact": "hook",
    "enforcement": "block",
    "provenance": {
        "author": "chock-core",
        "license": "Apache-2.0",
        "source_repo": "https://github.com/open-coder-ai/chock",
    },
}

RULE_MANIFEST = {
    "id": "code-safety",
    "name": "Code Safety Rule",
    "version": "0.0.1",
    "description": "Advisory rule with no gate.",
    "artifact": "rule",
    "enforcement": "advise",
    "rule": {"text": "never(commit): secrets|keys|tokens"},
}

GUARD_BODY = "#!/usr/bin/env bash\nexit 0  # test fixture guard\n"


@pytest.fixture
def policy(tmp_path: Path):
    def _make(manifest: dict, guard: bool = False) -> Path:
        pack = tmp_path / ".agents" / "policies" / manifest["id"]
        pack.mkdir(parents=True)
        (pack / "manifest.yaml").write_text(yaml.safe_dump(manifest), encoding="utf-8")
        if guard:
            impl = pack / "implementations"
            impl.mkdir()
            (impl / f"{manifest['id']}.sh").write_text(GUARD_BODY, encoding="utf-8")
        return pack

    return _make


def test_devin_guard_policy_layout_and_hook(policy, tmp_path: Path) -> None:
    files = devin_plugin_files(policy(GUARD_MANIFEST, guard=True), GUARD_MANIFEST, tmp_path)
    assert set(files) == {
        Path(".devin-plugin/plugin.json"),
        Path("skills/block-destructive-commands/SKILL.md"),
        Path("hooks.json"),
        Path("scripts/devin.py"),
        Path("scripts/launch.sh"),
        Path("scripts/block-destructive-commands.sh"),
    }

    hooks = json.loads(files[Path("hooks.json")])
    assert set(hooks) == {"PreToolUse"}, "devin's own hook_entry is bare: no top-level `hooks` wrapper"
    entry = hooks["PreToolUse"][0]
    assert "matcher" not in entry, "devin's shell-tool vocabulary is unrecorded, never invented"
    inner = entry["hooks"][0]
    assert inner["type"] == "command"
    assert inner["command"] == (
        guarded_launch("$DEVIN_PLUGIN_ROOT/scripts/launch.sh")
        + '"$DEVIN_PLUGIN_ROOT/scripts/devin.py" --guard "$DEVIN_PLUGIN_ROOT/scripts/block-destructive-commands.sh"'
    )


def test_devin_hooks_shape_matches_agentseams_own_hook_config(policy, tmp_path: Path) -> None:
    """The emitted file must honour agentseam's `bare` flag, not chock's own wrapping default."""
    from agentseam import adapters, contract

    files = devin_plugin_files(policy(GUARD_MANIFEST, guard=True), GUARD_MANIFEST, tmp_path)
    hooks = json.loads(files[Path("hooks.json")])
    command = hooks["PreToolUse"][0]["hooks"][0]["command"]

    upstream = adapters.get("devin").hook_config((contract.PRE_TOOL,), command, None)
    assert set(hooks) == set(upstream), "same top-level shape as agentseam's own hook_config for devin"
    upstream_inner = upstream["PreToolUse"][0]["hooks"][0]
    ours_inner = hooks["PreToolUse"][0]["hooks"][0]
    assert {**ours_inner, "timeout": None} == {**upstream_inner, "timeout": None}, (
        "identical modulo chock's own timeout key"
    )


def test_devin_manifest_is_native_layout(policy, tmp_path: Path) -> None:
    """`.devin-plugin/plugin.json` only, with the documented fields -- no interface/hooks key."""
    files = devin_plugin_files(policy(GUARD_MANIFEST, guard=True), GUARD_MANIFEST, tmp_path)
    assert Path("plugin.json") not in files, "a root plugin.json is the Agent Plugins 1.0 shape"
    assert Path(".codex-plugin/plugin.json") not in files
    data = json.loads(files[Path(".devin-plugin/plugin.json")])
    assert set(data) == {"name", "version", "description", "skills"}, "only documented manifest fields"
    assert data["skills"] == "skills"
    assert "hooks" not in data, "devin auto-discovers hooks.json at the plugin root; nothing declares it"
    assert Path("assets/icon.svg") not in files, "devin's manifest has no interface/composerIcon field"


def test_devin_rule_policy_gets_no_hook(policy, tmp_path: Path) -> None:
    files = devin_plugin_files(policy(RULE_MANIFEST), RULE_MANIFEST, tmp_path)
    assert set(files) == {Path(".devin-plugin/plugin.json"), Path("skills/code-safety/SKILL.md")}
    assert Path("LICENSE") not in files
    assert Path("hooks.json") not in files


def test_devin_adapter_and_guard_are_verbatim_copies(policy, tmp_path: Path) -> None:
    """Byte-identity is the contract: a plugin must not parse payloads differently from `chock sync`."""
    files = devin_plugin_files(policy(GUARD_MANIFEST, guard=True), GUARD_MANIFEST, tmp_path)
    assert files[Path("scripts/devin.py")] == runtime_bundle.render("devin")
    assert files[Path("scripts/block-destructive-commands.sh")] == GUARD_BODY


def test_devin_package_claims_match_the_package(policy, tmp_path: Path) -> None:
    """Description, skill frontmatter and closing note must all agree with the hook."""
    files = devin_plugin_files(policy(GUARD_MANIFEST, guard=True), GUARD_MANIFEST, tmp_path)
    assert POSTURE_BESTEFFORT_DEVIN in json.loads(files[Path(".devin-plugin/plugin.json")])["description"]

    skill = files[Path("skills/block-destructive-commands/SKILL.md")]
    meta = yaml.safe_load(skill.split("---")[1])["metadata"]
    assert meta["chock.hooks"] == "hooks.json"
    assert "chock.coverage_without_chock" not in meta
    assert "advisory: the client reading it has no mechanism to enforce it" not in skill


def test_devin_posture_never_claims_enforcement(policy, tmp_path: Path) -> None:
    """The vendor's own fail-open caveat, and no 'enforced'/'block' anywhere in the emitted text."""
    for forbidden in ("enforced", "block"):
        assert forbidden not in POSTURE_BESTEFFORT_DEVIN

    assert "best effort and fail open" in POSTURE_BESTEFFORT_DEVIN
    assert "don't rely on them for crucial guardrails yet" in POSTURE_BESTEFFORT_DEVIN
    assert "local Devin sessions (the CLI and Devin Desktop)" in POSTURE_BESTEFFORT_DEVIN
    assert "not witnessed" in POSTURE_BESTEFFORT_DEVIN
    assert "`chock sync`" in POSTURE_BESTEFFORT_DEVIN

    for forbidden in ("enforced", "enforces", "block"):
        assert forbidden not in _BESTEFFORT_NOTE_DEVIN, "the skill's closing note names no enforcement tier"


def test_devin_cli_builds_and_refuses_in_place(policy, tmp_path: Path, capsys) -> None:
    policy(GUARD_MANIFEST, guard=True)
    out = tmp_path / "dist"

    assert plugin_main(["build", "--repo", str(tmp_path), "--format", "devin"]) == 2, "in place must be refused"
    capsys.readouterr()
    assert plugin_main(["build", "--repo", str(tmp_path), "--format", "devin", "--out-dir", str(out)]) == 0
    capsys.readouterr()

    assert (out / "devin" / "block-destructive-commands" / ".devin-plugin" / "plugin.json").exists()
    assert (out / "devin" / "block-destructive-commands" / "hooks.json").exists()
    assert plugin_main(["build", "--repo", str(tmp_path), "--format", "devin", "--out-dir", str(out), "--check"]) == 0


def test_devin_losing_a_guard_removes_the_root_hook(policy, tmp_path: Path) -> None:
    """`hooks.json` sits at the plugin root; losing the guard must still remove it (store.py's"""
    pack = policy(GUARD_MANIFEST, guard=True)
    out = tmp_path / "dist" / "devin" / "block-destructive-commands"
    build_devin_plugin(pack, GUARD_MANIFEST, tmp_path, out)
    assert (out / "hooks.json").exists()

    (pack / "implementations" / "block-destructive-commands.sh").unlink()
    build_devin_plugin(pack, GUARD_MANIFEST, tmp_path, out)
    assert not (out / "hooks.json").exists()
    assert not (out / "scripts").exists()
