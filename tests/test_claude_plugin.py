"""Claude-format packaging: layout, verbatim copies, and the fail-posture statement.

The layout is mechanical; two properties matter. First, the adapter and guard ship as
byte-identical copies of their sources -- a plugin that parses payloads differently from a
repo install is two enforcement systems wearing one name. Second, every emitted
description states its fail posture out loud: a Claude plugin's PreToolUse hook fails OPEN
when python3 is missing, and a policy without a guard is advisory text however it is
packaged. A marketplace listing that overclaims enforcement is the one failure this
project cannot ship.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
import yaml

import chock.gate.pretooluse as adapter_module
from chock.plugin.build import build_skill
from chock.plugin.claude import (
    POSTURE_ADVISORY,
    POSTURE_ENFORCED,
    build_claude_plugin,
    claude_plugin_differences,
    claude_plugin_files,
)
from chock.plugin.cli import main as plugin_main

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


def test_guard_policy_ships_hooks_adapter_and_guard(policy, tmp_path: Path) -> None:
    pack = policy(GUARD_MANIFEST, guard=True)
    out = tmp_path / "dist" / "claude" / "block-destructive-commands"
    build_claude_plugin(pack, GUARD_MANIFEST, tmp_path, out)

    hooks = json.loads((out / "hooks" / "hooks.json").read_text(encoding="utf-8"))
    entry = hooks["hooks"]["PreToolUse"][0]
    assert entry["matcher"] == "Bash"
    command = entry["hooks"][0]["command"]
    assert "${CLAUDE_PLUGIN_ROOT}/scripts/pretooluse.py" in command
    assert "${CLAUDE_PLUGIN_ROOT}/scripts/block-destructive-commands.sh" in command
    # The fallback is load-bearing: on Windows, python3 is routinely the Store alias stub
    # that errors without running anything, and a client that treats a hook error as deny
    # (VS Code) then refuses every shell command. `||` is valid in sh, bash and cmd alike.
    assert command.startswith("python3 ")
    assert ' || python "' in command


def test_adapter_and_guard_are_verbatim_copies(policy, tmp_path: Path) -> None:
    """Byte-identity is the contract, not similarity.

    The adapter's own docstring promises "copied verbatim"; a plugin copy that drifted from
    the module would parse payloads differently from every repo install and the difference
    would surface only in someone else's session.
    """
    pack = policy(GUARD_MANIFEST, guard=True)
    out = tmp_path / "out"
    build_claude_plugin(pack, GUARD_MANIFEST, tmp_path, out)

    source = Path(adapter_module.__file__).read_text(encoding="utf-8")
    assert (out / "scripts" / "pretooluse.py").read_text(encoding="utf-8") == source
    assert (out / "scripts" / "block-destructive-commands.sh").read_text(encoding="utf-8") == GUARD_BODY


def test_descriptions_state_the_fail_posture(policy, tmp_path: Path) -> None:
    guarded = policy(GUARD_MANIFEST, guard=True)
    bare = policy(RULE_MANIFEST)

    guarded_manifest = claude_plugin_files(guarded, GUARD_MANIFEST, tmp_path)[Path(".claude-plugin/plugin.json")]
    bare_manifest = claude_plugin_files(bare, RULE_MANIFEST, tmp_path)[Path(".claude-plugin/plugin.json")]

    assert POSTURE_ENFORCED in json.loads(guarded_manifest)["description"]
    assert POSTURE_ADVISORY in json.loads(bare_manifest)["description"]
    # Both fail-open conditions must be named. The guards are bash scripts and the adapter
    # allows when it cannot find a usable bash, so a posture line mentioning only python3
    # would describe one of the two ways this plugin silently stops enforcing.
    assert "fails open" in POSTURE_ENFORCED, "the caveat is the load-bearing clause"
    assert "Python" in POSTURE_ENFORCED and "bash" in POSTURE_ENFORCED


def test_rule_policy_gets_no_hooks_or_scripts(policy, tmp_path: Path) -> None:
    """A policy with no guard must not grow one in packaging.

    Emitting an empty hooks file would read as "this plugin enforces" to anyone listing the
    directory -- the packaged version of the stale-surface-table overclaim.
    """
    pack = policy(RULE_MANIFEST)
    files = claude_plugin_files(pack, RULE_MANIFEST, tmp_path)
    assert set(files) == {Path(".claude-plugin/plugin.json"), Path("skills/code-safety/SKILL.md")}


def test_advisory_skill_is_the_shared_builder_output(policy, tmp_path: Path) -> None:
    """A guardless policy's skill is the shared builder's output, unmodified."""
    pack = policy(RULE_MANIFEST)
    files = claude_plugin_files(pack, RULE_MANIFEST, tmp_path)
    assert files[Path("skills/code-safety/SKILL.md")] == build_skill(pack, RULE_MANIFEST, tmp_path)


def test_enforcing_package_skill_does_not_call_itself_advisory(policy, tmp_path: Path) -> None:
    """The packaged skill must not contradict the hook shipped beside it.

    `build_skill` closes with "this skill is advisory: the client reading it has no mechanism
    to enforce it" -- true of the Agent Plugins package, false inside a Claude package that
    ships hooks.json. A file claiming nothing enforces this, sitting next to the thing that
    does, is a claim that does not match its own directory even though it under-claims.
    """
    pack = policy(GUARD_MANIFEST, guard=True)
    skill = claude_plugin_files(pack, GUARD_MANIFEST, tmp_path)[Path("skills/block-destructive-commands/SKILL.md")]
    assert "advisory: the client reading it has no mechanism to enforce it" not in skill
    assert "enforced in this client by a PreToolUse hook" in skill
    assert "`chock sync`" in skill, "repo-wide enforcement still has to be pointed at"


def test_output_is_byte_stable(policy, tmp_path: Path) -> None:
    pack = policy(GUARD_MANIFEST, guard=True)
    out = tmp_path / "out"
    build_claude_plugin(pack, GUARD_MANIFEST, tmp_path, out)
    first = {p: p.read_bytes() for p in sorted(out.rglob("*")) if p.is_file()}
    build_claude_plugin(pack, GUARD_MANIFEST, tmp_path, out)
    assert {p: p.read_bytes() for p in sorted(out.rglob("*")) if p.is_file()} == first


def test_check_detects_drift_and_writes_nothing(policy, tmp_path: Path) -> None:
    pack = policy(GUARD_MANIFEST, guard=True)
    out = tmp_path / "out"
    assert claude_plugin_differences(pack, GUARD_MANIFEST, tmp_path, out), "unbuilt tree should read as missing"
    assert not out.exists(), "--check must not create the tree it reports as missing"

    build_claude_plugin(pack, GUARD_MANIFEST, tmp_path, out)
    assert not claude_plugin_differences(pack, GUARD_MANIFEST, tmp_path, out)

    (out / "hooks" / "hooks.json").write_text("{}", encoding="utf-8")
    assert any("differs" in d for d in claude_plugin_differences(pack, GUARD_MANIFEST, tmp_path, out))


def test_cli_claude_format_requires_out_dir(policy, tmp_path: Path, capsys) -> None:
    """In-place claude output is refused, not defaulted.

    A `.claude-plugin/` directory inside a policy folder would be discovered by any client
    pointed at the repo and installed as a plugin nobody published.
    """
    policy(GUARD_MANIFEST, guard=True)
    assert plugin_main(["build", "--repo", str(tmp_path), "--format", "claude"]) == 2
    assert "--out-dir" in capsys.readouterr().err


def test_cli_builds_a_distribution_tree(policy, tmp_path: Path) -> None:
    policy(GUARD_MANIFEST, guard=True)
    policy(RULE_MANIFEST)
    dist = tmp_path / "dist"

    assert plugin_main(["build", "--repo", str(tmp_path), "--format", "all", "--out-dir", str(dist)]) == 0
    for plugin_id in ("block-destructive-commands", "code-safety"):
        # Each format owns its own subtree. They cannot share one: the Claude package of a
        # guard policy states the policy is enforced here, and the hookless Agent Plugins
        # package of the same policy states it is advisory. Both are true of their own
        # package, so a shared `skills/<id>/SKILL.md` would have to lie to one client.
        claude_root = dist / "claude" / plugin_id
        assert (claude_root / ".claude-plugin" / "plugin.json").exists()
        assert (claude_root / "skills" / plugin_id / "SKILL.md").exists()
        assert not (claude_root / "plugin.json").exists(), "the generic manifest lives in its own tree"

        generic_root = dist / "agent-plugins" / plugin_id
        assert (generic_root / "plugin.json").exists()
        assert (generic_root / "skills" / plugin_id / "SKILL.md").exists()
        assert not (generic_root / "hooks").exists(), "the standard defines no hooks"
    assert (dist / "claude" / "block-destructive-commands" / "hooks" / "hooks.json").exists()
    assert not (dist / "claude" / "code-safety" / "hooks").exists()

    assert plugin_main(["build", "--repo", str(tmp_path), "--format", "all", "--out-dir", str(dist), "--check"]) == 0
    (dist / "agent-plugins" / "code-safety" / "plugin.json").write_text("{}", encoding="utf-8")
    assert plugin_main(["build", "--repo", str(tmp_path), "--format", "all", "--out-dir", str(dist), "--check"]) == 1


def test_losing_a_guard_removes_its_hook(policy, tmp_path: Path) -> None:
    """A policy that stops shipping a guard must stop shipping the hook that ran it.

    Writing only current files would leave the old `hooks/hooks.json` and script in place:
    a package still denying commands while its own manifest and skill say it is advisory.
    That is this project's central failure -- a claim and a mechanism disagreeing -- arriving
    by omission rather than by assertion.
    """
    pack = policy(GUARD_MANIFEST, guard=True)
    out = tmp_path / "out"
    build_claude_plugin(pack, GUARD_MANIFEST, tmp_path, out)
    assert (out / "hooks" / "hooks.json").exists()

    (pack / "implementations" / "block-destructive-commands.sh").unlink()
    assert claude_plugin_differences(pack, GUARD_MANIFEST, tmp_path, out), "check reports the stale hook"

    build_claude_plugin(pack, GUARD_MANIFEST, tmp_path, out)
    assert not (out / "hooks").exists(), "the hook is gone, not merely unreferenced"
    assert not (out / "scripts").exists()
    assert not claude_plugin_differences(pack, GUARD_MANIFEST, tmp_path, out)


def test_check_reports_a_stale_hook_without_deleting_it(policy, tmp_path: Path) -> None:
    """`--check` judges; it does not repair. A check that fixed what it measured could not fail."""
    pack = policy(GUARD_MANIFEST, guard=True)
    out = tmp_path / "out"
    build_claude_plugin(pack, GUARD_MANIFEST, tmp_path, out)
    (pack / "implementations" / "block-destructive-commands.sh").unlink()

    assert any("stale" in d for d in claude_plugin_differences(pack, GUARD_MANIFEST, tmp_path, out))
    assert (out / "hooks" / "hooks.json").exists(), "check must not delete what it reports"


def test_a_removed_policy_stops_being_published(policy, tmp_path: Path) -> None:
    """A withdrawn policy must leave the distribution, or the yank procedure fails silently."""
    policy(GUARD_MANIFEST, guard=True)
    bare = policy(RULE_MANIFEST)
    dist = tmp_path / "dist"
    assert plugin_main(["build", "--repo", str(tmp_path), "--format", "all", "--out-dir", str(dist)]) == 0
    assert (dist / "claude" / "code-safety").is_dir()

    shutil.rmtree(bare)
    assert plugin_main(["build", "--repo", str(tmp_path), "--format", "all", "--out-dir", str(dist), "--check"]) == 1

    assert plugin_main(["build", "--repo", str(tmp_path), "--format", "all", "--out-dir", str(dist)]) == 0
    assert not (dist / "claude" / "code-safety").exists()
    assert not (dist / "agent-plugins" / "code-safety").exists()
    assert (dist / "claude" / "block-destructive-commands").is_dir(), "the surviving policy is untouched"


def test_duplicate_policy_ids_are_refused(policy, tmp_path: Path, capsys) -> None:
    """Two folders declaring one id would package into one directory, the second winning.

    The run would report both as packaged while the distribution contained a single package
    built from a mixture of the two -- so this refuses rather than picking a winner.
    """
    policy(GUARD_MANIFEST, guard=True)
    twin = dict(RULE_MANIFEST)
    twin["id"] = "block-destructive-commands"
    pack = tmp_path / ".agents" / "policies" / "a-different-folder"
    pack.mkdir(parents=True)
    (pack / "manifest.yaml").write_text(yaml.safe_dump(twin), encoding="utf-8")

    dist = tmp_path / "dist"
    assert plugin_main(["build", "--repo", str(tmp_path), "--format", "all", "--out-dir", str(dist)]) == 2
    assert "duplicate policy id" in capsys.readouterr().err
