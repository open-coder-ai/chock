"""Cursor and Codex packaging: the envelope differs, the enforcement does not."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from chock.gate import runtime_bundle
from chock.plugin.cli import main as plugin_main
from chock.plugin.codex import POSTURE_ENFORCED_CODEX, build_codex_plugin, codex_plugin_files
from chock.plugin.cursor import POSTURE_ENFORCED_CURSOR, build_cursor_plugin, cursor_plugin_files

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


def test_cursor_guard_policy_layout_and_hook(policy, tmp_path: Path) -> None:
    files = cursor_plugin_files(policy(GUARD_MANIFEST, guard=True), GUARD_MANIFEST, tmp_path)
    assert set(files) == {
        Path(".cursor-plugin/plugin.json"),
        Path("skills/block-destructive-commands/SKILL.md"),
        Path("hooks/hooks.json"),
        Path("scripts/cursor.py"),
        Path("scripts/block-destructive-commands.sh"),
    }

    hooks = json.loads(files[Path("hooks/hooks.json")])
    assert hooks["version"] == 1
    entries = hooks["hooks"]["beforeShellExecution"]
    assert len(entries) == 1
    entry = entries[0]
    assert set(entry) == {"command", "timeout"}
    assert entry["command"] == (
        'python3 "${CURSOR_PLUGIN_ROOT}/scripts/cursor.py" '
        '--guard "${CURSOR_PLUGIN_ROOT}/scripts/block-destructive-commands.sh"'
    )


def test_cursor_hook_carries_no_matcher(policy, tmp_path: Path) -> None:
    """A `matcher` here is a regex over the command text, not a tool name."""
    files = cursor_plugin_files(policy(GUARD_MANIFEST, guard=True), GUARD_MANIFEST, tmp_path)
    entry = json.loads(files[Path("hooks/hooks.json")])["hooks"]["beforeShellExecution"][0]
    assert "matcher" not in entry
    assert "failClosed" not in entry


def test_cursor_manifest_rejects_agent_plugins_keys(policy, tmp_path: Path) -> None:
    """Cursor's schema is additionalProperties:false -- `$schema`/`extensions` invalidate it."""
    files = cursor_plugin_files(policy(GUARD_MANIFEST, guard=True), GUARD_MANIFEST, tmp_path)
    data = json.loads(files[Path(".cursor-plugin/plugin.json")])
    assert "$schema" not in data
    assert "extensions" not in data
    assert data["skills"] == "./skills/"
    assert data["hooks"] == "./hooks/hooks.json"
    assert data["category"] == "developer-tools"
    assert set(data["author"]) <= {"name", "email"}, "author is additionalProperties:false"


def test_cursor_rule_policy_gets_no_hook(policy, tmp_path: Path) -> None:
    files = cursor_plugin_files(policy(RULE_MANIFEST), RULE_MANIFEST, tmp_path)
    assert set(files) == {Path(".cursor-plugin/plugin.json"), Path("skills/code-safety/SKILL.md")}
    assert "hooks" not in json.loads(files[Path(".cursor-plugin/plugin.json")])


def test_codex_guard_policy_layout_and_hook(policy, tmp_path: Path) -> None:
    files = codex_plugin_files(policy(GUARD_MANIFEST, guard=True), GUARD_MANIFEST, tmp_path)
    assert set(files) == {
        Path(".codex-plugin/plugin.json"),
        Path("skills/block-destructive-commands/SKILL.md"),
        Path("hooks/hooks.json"),
        Path("scripts/codex_cli.py"),
        Path("scripts/block-destructive-commands.sh"),
        Path("assets/icon.svg"),
    }

    hooks = json.loads(files[Path("hooks/hooks.json")])
    assert set(hooks) == {"hooks"}
    entry = hooks["hooks"]["PreToolUse"][0]
    assert entry["matcher"] == "Bash"
    inner = entry["hooks"][0]
    assert inner["type"] == "command"
    assert "async" not in inner, "Codex only honours a blocking decision from a sync hook"
    assert inner["command"] == (
        'python3 "${PLUGIN_ROOT}/scripts/codex_cli.py" --guard "${PLUGIN_ROOT}/scripts/block-destructive-commands.sh"'
    )


def test_codex_manifest_is_legacy_format_not_agent_plugins(policy, tmp_path: Path) -> None:
    """The manifest must be `.codex-plugin/plugin.json` WITHOUT the agent-plugins `$schema`."""
    files = codex_plugin_files(policy(GUARD_MANIFEST, guard=True), GUARD_MANIFEST, tmp_path)
    assert Path("plugin.json") not in files, "a root plugin.json is the AgentPlugin shape"
    data = json.loads(files[Path(".codex-plugin/plugin.json")])
    assert "$schema" not in data
    assert "extensions" not in data
    assert data["hooks"] == "./hooks/hooks.json"


def test_codex_rule_policy_gets_no_hook(policy, tmp_path: Path) -> None:
    files = codex_plugin_files(policy(RULE_MANIFEST), RULE_MANIFEST, tmp_path)
    assert set(files) == {
        Path(".codex-plugin/plugin.json"),
        Path("skills/code-safety/SKILL.md"),
        Path("assets/icon.svg"),
    }
    assert Path("LICENSE") not in files
    assert "hooks" not in json.loads(files[Path(".codex-plugin/plugin.json")])


@pytest.mark.parametrize(
    "files_for,manifest_rel,script_name,agent",
    [
        (cursor_plugin_files, Path(".cursor-plugin/plugin.json"), "cursor.py", "cursor"),
        (codex_plugin_files, Path(".codex-plugin/plugin.json"), "codex_cli.py", "codex_cli"),
    ],
)
def test_adapter_and_guard_are_verbatim_copies(
    policy, tmp_path: Path, files_for, manifest_rel, script_name, agent
) -> None:
    """Byte-identity is the contract: a plugin must not parse payloads differently from"""
    files = files_for(policy(GUARD_MANIFEST, guard=True), GUARD_MANIFEST, tmp_path)
    assert files[Path("scripts") / script_name] == runtime_bundle.render(agent)
    assert files[Path("scripts/block-destructive-commands.sh")] == GUARD_BODY
    assert manifest_rel in files


@pytest.mark.parametrize(
    "files_for,manifest_rel,posture,hook_path",
    [
        (cursor_plugin_files, Path(".cursor-plugin/plugin.json"), POSTURE_ENFORCED_CURSOR, "hooks/hooks.json"),
        (codex_plugin_files, Path(".codex-plugin/plugin.json"), POSTURE_ENFORCED_CODEX, "hooks/hooks.json"),
    ],
)
def test_enforced_package_claims_match_the_package(
    policy, tmp_path: Path, files_for, manifest_rel, posture, hook_path
) -> None:
    """Description, skill frontmatter and closing note must all agree with the hook."""
    files = files_for(policy(GUARD_MANIFEST, guard=True), GUARD_MANIFEST, tmp_path)
    assert posture in json.loads(files[manifest_rel])["description"]

    skill = files[Path("skills/block-destructive-commands/SKILL.md")]
    meta = yaml.safe_load(skill.split("---")[1])["metadata"]
    assert meta["chock.hooks"] == hook_path
    assert "chock.coverage_without_chock" not in meta
    assert "advisory: the client reading it has no mechanism to enforce it" not in skill


def test_cli_builds_both_formats_and_refuses_in_place(policy, tmp_path: Path, capsys) -> None:
    policy(GUARD_MANIFEST, guard=True)
    out = tmp_path / "dist"

    for fmt in ("cursor", "codex"):
        assert plugin_main(["build", "--repo", str(tmp_path), "--format", fmt]) == 2, "in place must be refused"
        capsys.readouterr()
        assert plugin_main(["build", "--repo", str(tmp_path), "--format", fmt, "--out-dir", str(out)]) == 0
        capsys.readouterr()

    assert (out / "cursor" / "block-destructive-commands" / ".cursor-plugin" / "plugin.json").exists()
    assert (out / "codex" / "block-destructive-commands" / ".codex-plugin" / "plugin.json").exists()
    for fmt in ("cursor", "codex"):
        assert plugin_main(["build", "--repo", str(tmp_path), "--format", fmt, "--out-dir", str(out), "--check"]) == 0
        capsys.readouterr()


@pytest.mark.parametrize(
    "build,tree,hook_rel",
    [
        (build_cursor_plugin, "cursor", Path("hooks/hooks.json")),
        (build_codex_plugin, "codex", Path("hooks/hooks.json")),
    ],
)
def test_losing_a_guard_removes_the_hook(policy, tmp_path: Path, build, tree, hook_rel) -> None:
    """A package that loses its guard must lose its hook, or it enforces what it no longer claims."""
    pack = policy(GUARD_MANIFEST, guard=True)
    out = tmp_path / "dist" / tree / "block-destructive-commands"
    build(pack, GUARD_MANIFEST, tmp_path, out)
    assert (out / hook_rel).exists()

    (pack / "implementations" / "block-destructive-commands.sh").unlink()
    build(pack, GUARD_MANIFEST, tmp_path, out)
    assert not (out / hook_rel).exists()
    assert not (out / "scripts").exists()


def test_each_vendor_claims_only_what_was_witnessed(policy, tmp_path: Path) -> None:
    """Cursor was witnessed blocking; Codex was witnessed NOT blocking. The packages say so."""
    assert "Session-enforced in Cursor" in POSTURE_ENFORCED_CURSOR
    assert "OPEN" in POSTURE_ENFORCED_CURSOR and "python3" in POSTURE_ENFORCED_CURSOR

    assert "Session-enforced in Codex" in POSTURE_ENFORCED_CODEX, "witnessed 2026-08-24"
    assert "trust review" in POSTURE_ENFORCED_CODEX, "hooks are inert until a human approves"
    assert "update voids that trust" in POSTURE_ENFORCED_CODEX, "the upgrade fail-open must be named"
    assert "OPEN" in POSTURE_ENFORCED_CODEX, "hook failures fail open and the posture says so"
    assert "`chock sync`" in POSTURE_ENFORCED_CODEX, "repo-level enforcement still pointed at"
