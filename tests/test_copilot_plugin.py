"""Copilot-format packaging: spec-shaped layout, shared enforcement, honest claims.

This format exists because awesome-copilot's intake validates against the Agent Plugins
1.0 spec (`vally lint` + an install smoke test that requires `plugin.json` at the package
root), which the Claude layout is not. Three properties matter. First, the layout is the
spec's: root manifest, `skills/`, and the hook under the `com.github.copilot/` namespace
directory a non-Copilot client MUST ignore. Second, the adapter and guard bytes are
byte-identical to the Claude package's, and the hook command matches it except for the
plugin-root token (this format resolves ${PLUGIN_ROOT}, Claude's resolves
${CLAUDE_PLUGIN_ROOT}) -- one enforcement system, two formats. Third, the SKILL.md
frontmatter `metadata` is a flat string-to-string map, the constraint the original nested
object violated and awesome-copilot rejected.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from chock.gate import runtime_bundle
from chock.plugin.build import build_skill
from chock.plugin.claude import POSTURE_ADVISORY
from chock.plugin.cli import main as plugin_main
from chock.plugin.copilot import (
    POSTURE_ENFORCED_COPILOT,
    build_copilot_plugin,
    copilot_plugin_differences,
    copilot_plugin_files,
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


def test_manifest_is_at_the_package_root(policy, tmp_path: Path) -> None:
    """`plugin.json` at the root is the property awesome-copilot's smoke test requires.

    The Claude layout keeps it in `.claude-plugin/`, which their validator reports as "no
    plugin.json found in a recognized location" -- the exact intake failure this format
    exists to fix.
    """
    pack = policy(GUARD_MANIFEST, guard=True)
    files = copilot_plugin_files(pack, GUARD_MANIFEST, tmp_path)
    assert Path("plugin.json") in files
    manifest = json.loads(files[Path("plugin.json")])
    assert manifest["$schema"] == "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json"
    assert manifest["name"] == "block-destructive-commands"


def test_hook_lives_in_the_copilot_namespace(policy, tmp_path: Path) -> None:
    pack = policy(GUARD_MANIFEST, guard=True)
    out = tmp_path / "dist" / "copilot" / "block-destructive-commands"
    build_copilot_plugin(pack, GUARD_MANIFEST, tmp_path, out)

    hooks = json.loads((out / "com.github.copilot" / "hooks" / "hooks.json").read_text(encoding="utf-8"))
    entry = hooks["hooks"]["PreToolUse"][0]
    assert entry["matcher"] == "Bash"
    command = entry["hooks"][0]["command"]
    # The EXACT command: changing this string changes enforcement. The root is an
    # environment VARIABLE, not a `${PLUGIN_ROOT}` token, and an unresolved root exits 0 --
    # both load-bearing, see tests/test_copilot_hook_runtime.py. This once pinned a command
    # that denied every tool call: a pinned string proves intent, not function.
    assert command == (
        'r="${PLUGIN_ROOT:-}"; [ -n "$r" ] && [ -f "$r/scripts/vscode_copilot.py" ] || exit 0; '
        'exec python3 "$r/scripts/vscode_copilot.py" '
        '--guard "$r/scripts/block-destructive-commands.sh"'
    )


def test_adapter_and_guard_are_verbatim_copies(policy, tmp_path: Path) -> None:
    pack = policy(GUARD_MANIFEST, guard=True)
    out = tmp_path / "out"
    build_copilot_plugin(pack, GUARD_MANIFEST, tmp_path, out)

    source = runtime_bundle.render("vscode_copilot")
    assert (out / "scripts" / "vscode_copilot.py").read_text(encoding="utf-8") == source
    assert (out / "scripts" / "block-destructive-commands.sh").read_text(encoding="utf-8") == GUARD_BODY


def test_skill_metadata_is_a_flat_string_map(policy, tmp_path: Path) -> None:
    """The Agent Skills spec constraint the original packaging violated.

    `metadata` must map string keys to string values; the nested `chock:` object was
    rejected by awesome-copilot's `vally` linter ("Metadata values must be strings").
    Parsed, not substring-matched, so a regression to any non-string value fails whatever
    its key is called.
    """
    pack = policy(RULE_MANIFEST)
    skill = build_skill(pack, RULE_MANIFEST, tmp_path)
    frontmatter = yaml.safe_load(skill.split("---")[1])
    metadata = frontmatter["metadata"]
    assert metadata, "the chock metadata must still be present"
    for key, value in metadata.items():
        assert isinstance(key, str) and isinstance(value, str), (
            f"metadata[{key!r}] = {value!r}: the Agent Skills spec requires string keys to string values"
        )


def test_descriptions_state_the_fail_posture(policy, tmp_path: Path) -> None:
    """The copilot posture is scoped to this format's audience, not borrowed from Claude's.

    Generic Agent Plugins clients are REQUIRED to ignore `com.github.copilot`, so an
    unqualified "session-enforced" would overclaim to exactly the readers this layout
    exists for. The posture must name where the hook enforces, what a namespace-ignoring
    client gets, and claim only what is verified (VS Code documents the location).
    """
    guarded = policy(GUARD_MANIFEST, guard=True)
    bare = policy(RULE_MANIFEST)

    guarded_manifest = json.loads(copilot_plugin_files(guarded, GUARD_MANIFEST, tmp_path)[Path("plugin.json")])
    bare_manifest = json.loads(copilot_plugin_files(bare, RULE_MANIFEST, tmp_path)[Path("plugin.json")])

    assert POSTURE_ENFORCED_COPILOT in guarded_manifest["description"]
    assert POSTURE_ADVISORY in bare_manifest["description"]
    assert "com.github.copilot" in POSTURE_ENFORCED_COPILOT, "the scope must be named"
    assert "ignores it" in POSTURE_ENFORCED_COPILOT, "the namespace-ignoring outcome must be named"
    assert "python3" in POSTURE_ENFORCED_COPILOT and "bash" in POSTURE_ENFORCED_COPILOT


def test_extension_claims_match_the_package_contents(policy, tmp_path: Path) -> None:
    """`coverage_without_chock: advisory` means "ignore our namespace and you get advisory
    text and nothing else". True of a hookless package; false of one whose hook enforces in
    any client honouring `com.github.copilot`, chock or no chock. Each package carries the
    claim that is true of it."""
    namespace = "io.github.open-coder-ai"
    guarded = policy(GUARD_MANIFEST, guard=True)
    bare = policy(RULE_MANIFEST)

    guarded_ext = json.loads(copilot_plugin_files(guarded, GUARD_MANIFEST, tmp_path)[Path("plugin.json")])[
        "extensions"
    ][namespace]
    bare_ext = json.loads(copilot_plugin_files(bare, RULE_MANIFEST, tmp_path)[Path("plugin.json")])["extensions"][
        namespace
    ]

    assert guarded_ext["hooks"] == "com.github.copilot/hooks/hooks.json"
    assert "coverage_without_chock" not in guarded_ext
    assert bare_ext["coverage_without_chock"] == "advisory"
    assert "hooks" not in bare_ext
    # build_manifest's `manifest: manifest.yaml` pointer resolves only in the in-place
    # agent-plugins mode. This format always builds out-of-place and ships no
    # manifest.yaml, so keeping the pointer would name a file the package does not contain.
    assert "manifest" not in guarded_ext and "manifest" not in bare_ext


def test_rule_policy_gets_no_hooks_or_scripts(policy, tmp_path: Path) -> None:
    pack = policy(RULE_MANIFEST)
    files = copilot_plugin_files(pack, RULE_MANIFEST, tmp_path)
    assert set(files) == {Path("plugin.json"), Path("skills/code-safety/SKILL.md")}


def test_enforcing_package_skill_does_not_call_itself_advisory(policy, tmp_path: Path) -> None:
    """The closing note is the copilot-scoped one, not the Claude package's.

    The Claude note says "enforced in this client", which presumes the reader's client
    ran the hook -- true for a Claude-layout reader, false for a generic Agent Plugins
    client that ignored the namespace. The copilot note names the scope instead.
    """
    pack = policy(GUARD_MANIFEST, guard=True)
    skill = copilot_plugin_files(pack, GUARD_MANIFEST, tmp_path)[Path("skills/block-destructive-commands/SKILL.md")]
    assert "advisory: the client reading it has no mechanism to enforce it" not in skill
    assert "ships a PreToolUse hook under com.github.copilot/" in skill
    assert "ignores the namespace gets this text only" in skill
    assert "`chock sync`" in skill, "repo-wide enforcement still has to be pointed at"


def test_output_is_byte_stable(policy, tmp_path: Path) -> None:
    pack = policy(GUARD_MANIFEST, guard=True)
    out = tmp_path / "out"
    build_copilot_plugin(pack, GUARD_MANIFEST, tmp_path, out)
    first = {p: p.read_bytes() for p in sorted(out.rglob("*")) if p.is_file()}
    build_copilot_plugin(pack, GUARD_MANIFEST, tmp_path, out)
    assert {p: p.read_bytes() for p in sorted(out.rglob("*")) if p.is_file()} == first


def test_losing_a_guard_removes_its_hook(policy, tmp_path: Path) -> None:
    """Same reconciliation contract as the Claude format, same reason: a package still
    denying commands its own manifest now calls advisory is a claim/mechanism mismatch
    arriving by omission."""
    pack = policy(GUARD_MANIFEST, guard=True)
    out = tmp_path / "out"
    build_copilot_plugin(pack, GUARD_MANIFEST, tmp_path, out)
    assert (out / "com.github.copilot" / "hooks" / "hooks.json").exists()

    (pack / "implementations" / "block-destructive-commands.sh").unlink()
    assert copilot_plugin_differences(pack, GUARD_MANIFEST, tmp_path, out), "check reports the stale hook"

    build_copilot_plugin(pack, GUARD_MANIFEST, tmp_path, out)
    assert not (out / "com.github.copilot").exists(), "the namespace dir is gone, not merely unreferenced"
    assert not (out / "scripts").exists()
    assert not copilot_plugin_differences(pack, GUARD_MANIFEST, tmp_path, out)


def test_check_detects_drift_and_writes_nothing(policy, tmp_path: Path) -> None:
    pack = policy(GUARD_MANIFEST, guard=True)
    out = tmp_path / "out"
    assert copilot_plugin_differences(pack, GUARD_MANIFEST, tmp_path, out), "unbuilt tree should read as missing"
    assert not out.exists(), "--check must not create the tree it reports as missing"

    build_copilot_plugin(pack, GUARD_MANIFEST, tmp_path, out)
    assert not copilot_plugin_differences(pack, GUARD_MANIFEST, tmp_path, out)

    (out / "com.github.copilot" / "hooks" / "hooks.json").write_text("{}", encoding="utf-8")
    assert any("differs" in d for d in copilot_plugin_differences(pack, GUARD_MANIFEST, tmp_path, out))


def test_cli_copilot_format_requires_out_dir(policy, tmp_path: Path, capsys) -> None:
    policy(GUARD_MANIFEST, guard=True)
    assert plugin_main(["build", "--repo", str(tmp_path), "--format", "copilot"]) == 2
    assert "--out-dir" in capsys.readouterr().err


def test_cli_all_builds_the_copilot_tree_too(policy, tmp_path: Path) -> None:
    policy(GUARD_MANIFEST, guard=True)
    policy(RULE_MANIFEST)
    dist = tmp_path / "dist"

    assert plugin_main(["build", "--repo", str(tmp_path), "--format", "all", "--out-dir", str(dist)]) == 0
    root = dist / "copilot" / "block-destructive-commands"
    assert (root / "plugin.json").exists()
    assert (root / "skills" / "block-destructive-commands" / "SKILL.md").exists()
    assert (root / "com.github.copilot" / "hooks" / "hooks.json").exists()
    assert not (dist / "copilot" / "code-safety" / "com.github.copilot").exists()

    assert plugin_main(["build", "--repo", str(tmp_path), "--format", "all", "--out-dir", str(dist), "--check"]) == 0
    (root / "plugin.json").write_text("{}", encoding="utf-8")
    assert plugin_main(["build", "--repo", str(tmp_path), "--format", "all", "--out-dir", str(dist), "--check"]) == 1
