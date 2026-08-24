"""Cursor and Codex packaging: the envelope differs, the enforcement does not.

Both vendors run the same guard through the same adapter as the Claude package; what
changes is the file layout, the event name and the hook shape. These tests pin the parts
that are vendor-specific and easy to get silently wrong:

- Cursor's `beforeShellExecution` matcher is a regex over the COMMAND TEXT, not a tool
  name, so emitting the other formats' `MATCHER = "Bash"` would match almost nothing and
  disable the guard while the package still claimed enforcement.
- Codex DISCARDS hooks from an Agent-Plugins-format manifest (loader.rs), so the manifest
  must be `.codex-plugin/plugin.json` and must not carry the agent-plugins `$schema`.
- Cursor's manifest schema is `additionalProperties: false`, so `$schema`/`extensions`
  (which the shared `build_manifest` emits) would make the package invalid.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

import chock.gate.pretooluse as adapter_module
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


# ----------------------------------------------------------------------------- cursor


def test_cursor_guard_policy_layout_and_hook(policy, tmp_path: Path) -> None:
    files = cursor_plugin_files(policy(GUARD_MANIFEST, guard=True), GUARD_MANIFEST, tmp_path)
    assert set(files) == {
        Path(".cursor-plugin/plugin.json"),
        Path("skills/block-destructive-commands/SKILL.md"),
        Path("hooks/hooks.json"),
        Path("scripts/pretooluse.py"),
        Path("scripts/block-destructive-commands.sh"),
    }

    hooks = json.loads(files[Path("hooks/hooks.json")])
    assert hooks["version"] == 1
    entries = hooks["hooks"]["beforeShellExecution"]
    assert len(entries) == 1
    entry = entries[0]
    # Flat entry: no nested `hooks` array and no `type`, unlike Claude/Codex.
    assert set(entry) == {"command", "timeout"}
    # The exact command, not properties of it: one interpreter invocation, no fallback
    # chain (a chain converts a real deny into the next leg's exit code).
    assert entry["command"] == (
        'python3 "${CURSOR_PLUGIN_ROOT}/scripts/pretooluse.py" '
        '--guard "${CURSOR_PLUGIN_ROOT}/scripts/block-destructive-commands.sh"'
    )


def test_cursor_hook_carries_no_matcher(policy, tmp_path: Path) -> None:
    """A `matcher` here is a regex over the command text, not a tool name.

    Emitting the Claude/Codex `MATCHER = "Bash"` would be read as a command regex and
    match almost nothing -- a package that ships a hook, claims enforcement, and silently
    never fires.
    """
    files = cursor_plugin_files(policy(GUARD_MANIFEST, guard=True), GUARD_MANIFEST, tmp_path)
    entry = json.loads(files[Path("hooks/hooks.json")])["hooks"]["beforeShellExecution"][0]
    assert "matcher" not in entry
    # failClosed is likewise deliberately absent: the plugin resolves python3 at run time,
    # so failing closed would refuse every shell command on a machine without it.
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


# ------------------------------------------------------------------------------ codex


def test_codex_guard_policy_layout_and_hook(policy, tmp_path: Path) -> None:
    files = codex_plugin_files(policy(GUARD_MANIFEST, guard=True), GUARD_MANIFEST, tmp_path)
    assert set(files) == {
        Path(".codex-plugin/plugin.json"),
        Path("skills/block-destructive-commands/SKILL.md"),
        Path("hooks/hooks.json"),
        Path("scripts/pretooluse.py"),
        Path("scripts/block-destructive-commands.sh"),
    }

    hooks = json.loads(files[Path("hooks/hooks.json")])
    # Codex parses the top level with deny_unknown_fields: exactly these two keys.
    assert set(hooks) == {"description", "hooks"}
    entry = hooks["hooks"]["PreToolUse"][0]
    assert entry["matcher"] == "Bash"
    inner = entry["hooks"][0]
    assert inner["type"] == "command"
    assert "async" not in inner, "Codex only honours a blocking decision from a sync hook"
    assert inner["command"] == (
        'python3 "${PLUGIN_ROOT}/scripts/pretooluse.py" --guard "${PLUGIN_ROOT}/scripts/block-destructive-commands.sh"'
    )


def test_codex_manifest_is_legacy_format_not_agent_plugins(policy, tmp_path: Path) -> None:
    """The manifest must be `.codex-plugin/plugin.json` WITHOUT the agent-plugins `$schema`.

    Codex's loader discards hooks when it classifies a manifest as AgentPlugin format, so
    an agent-plugins-shaped manifest would install a package whose hook is deleted at load
    time while its description still claimed enforcement.
    """
    files = codex_plugin_files(policy(GUARD_MANIFEST, guard=True), GUARD_MANIFEST, tmp_path)
    assert Path("plugin.json") not in files, "a root plugin.json is the AgentPlugin shape"
    data = json.loads(files[Path(".codex-plugin/plugin.json")])
    assert "$schema" not in data
    assert "extensions" not in data
    assert data["hooks"] == "./hooks/hooks.json"


def test_codex_rule_policy_gets_no_hook(policy, tmp_path: Path) -> None:
    files = codex_plugin_files(policy(RULE_MANIFEST), RULE_MANIFEST, tmp_path)
    assert set(files) == {Path(".codex-plugin/plugin.json"), Path("skills/code-safety/SKILL.md")}
    assert "hooks" not in json.loads(files[Path(".codex-plugin/plugin.json")])


# -------------------------------------------------------------------- shared discipline


@pytest.mark.parametrize(
    "files_for,manifest_rel",
    [
        (cursor_plugin_files, Path(".cursor-plugin/plugin.json")),
        (codex_plugin_files, Path(".codex-plugin/plugin.json")),
    ],
)
def test_adapter_and_guard_are_verbatim_copies(policy, tmp_path: Path, files_for, manifest_rel) -> None:
    """Byte-identity is the contract: a plugin must not parse payloads differently."""
    files = files_for(policy(GUARD_MANIFEST, guard=True), GUARD_MANIFEST, tmp_path)
    assert files[Path("scripts/pretooluse.py")] == Path(adapter_module.__file__).read_text(encoding="utf-8")
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
    # Both vendors are fail-open, and saying so is the whole posture discipline.
    assert "OPEN" in posture and "python3" in posture

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
    # --check is clean immediately after a build, and writes nothing.
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
