"""Marketplace index emission: derived-only, byte-identical mirrors, loud on empty.

The index is a claim about what the distribution repo publishes. Three properties keep
that claim honest: entries are derived from the built plugin manifests (never a second
hand-maintained list), the Claude and Copilot index paths carry byte-identical content
(Copilot's official marketplace uses a symlink; we emit a copy for Windows checkouts), and
an empty tree refuses to produce an index rather than silently delisting every plugin.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from chock.plugin.cli import main as plugin_main
from chock.plugin.marketplace import DESCRIPTION, INDEX_PATHS, LOCKFILE_NAME
from chock.plugin.marketplace import main as marketplace_main

MANIFESTS = [
    {
        "id": "block-destructive-commands",
        "name": "Block Destructive Commands",
        "version": "0.0.2",
        "description": "Block rm -rf and friends before they run.",
        "artifact": "hook",
        "enforcement": "block",
    },
    {
        "id": "code-safety",
        "name": "Code Safety Rule",
        "version": "0.0.1",
        "description": "Advisory rule with no gate.",
        "artifact": "rule",
        "enforcement": "advise",
        "rule": {"text": "never(commit): secrets"},
    },
]


@pytest.fixture
def dist(tmp_path: Path) -> Path:
    """A built distribution tree: two policies rendered by the real plugin CLI."""
    for manifest in MANIFESTS:
        pack = tmp_path / ".agents" / "policies" / manifest["id"]
        pack.mkdir(parents=True)
        (pack / "manifest.yaml").write_text(yaml.safe_dump(manifest), encoding="utf-8")
        if manifest["artifact"] == "hook":
            impl = pack / "implementations"
            impl.mkdir()
            (impl / f"{manifest['id']}.sh").write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    out = tmp_path / "dist"
    assert plugin_main(["build", "--repo", str(tmp_path), "--format", "all", "--out-dir", str(out)]) == 0
    return out


def test_both_index_paths_carry_identical_bytes(dist: Path) -> None:
    assert marketplace_main(["build", "--dist", str(dist)]) == 0
    contents = [(dist / rel).read_bytes() for rel in INDEX_PATHS]
    assert contents[0] == contents[1]
    assert len(INDEX_PATHS) == 2


def test_entries_are_derived_from_the_built_manifests(dist: Path) -> None:
    marketplace_main(["build", "--dist", str(dist)])
    index = json.loads((dist / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8"))

    assert index["name"] == "chock"
    # `claude plugin validate` warns without it, and it is what a browsing user reads
    # before trusting the source -- so it names the origin and the enforcement caveat.
    assert index["description"] == DESCRIPTION
    assert "advisory" in DESCRIPTION, "the caveat belongs in the first thing a user reads"
    assert [e["name"] for e in index["plugins"]] == ["block-destructive-commands", "code-safety"], "sorted"
    for entry in index["plugins"]:
        assert entry["source"] == f"./claude/{entry['name']}"
        built = json.loads(
            (dist / "claude" / entry["name"] / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8")
        )
        assert entry["description"] == built["description"], "the index repeats the manifest, never rewrites it"
        assert entry["version"] == built["version"]


def test_check_detects_drift_and_missing(dist: Path, capsys) -> None:
    assert marketplace_main(["build", "--dist", str(dist), "--check"]) == 1, "missing index fails the check"
    assert not (dist / ".claude-plugin" / "marketplace.json").exists(), "--check must write nothing"

    marketplace_main(["build", "--dist", str(dist)])
    assert marketplace_main(["build", "--dist", str(dist), "--check"]) == 0

    (dist / ".github" / "plugin" / "marketplace.json").write_text("{}", encoding="utf-8")
    assert marketplace_main(["build", "--dist", str(dist), "--check"]) == 1
    assert "differs" in capsys.readouterr().out


def test_empty_tree_refuses_to_index(tmp_path: Path, capsys) -> None:
    assert marketplace_main(["build", "--dist", str(tmp_path)]) == 2
    assert "refusing to write an empty index" in capsys.readouterr().err
    for rel in INDEX_PATHS:
        assert not (tmp_path / rel).exists()


def test_output_is_byte_stable(dist: Path) -> None:
    marketplace_main(["build", "--dist", str(dist)])
    first = [(dist / rel).read_bytes() for rel in INDEX_PATHS]
    marketplace_main(["build", "--dist", str(dist)])
    assert [(dist / rel).read_bytes() for rel in INDEX_PATHS] == first


def test_lockfile_content_addresses_every_published_directory(dist: Path) -> None:
    """One sha256 per plugin directory, across every format tree.

    This is what lets an auditor or a `require_sha` fleet check that the directory they
    received is the one that was published, without trusting the index or the commit
    history to have been honest about it.
    """
    import json as _json

    marketplace_main(["build", "--dist", str(dist)])
    lock = _json.loads((dist / LOCKFILE_NAME).read_text(encoding="utf-8"))

    assert lock["lockfile_version"] == 1
    assert set(lock["plugins"]) == {
        "claude/block-destructive-commands",
        "claude/code-safety",
        "agent-plugins/block-destructive-commands",
        "agent-plugins/code-safety",
    }, "every tree is covered, not just the one the index points at"
    assert all(len(h) == 64 for h in lock["plugins"].values())
    assert (
        lock["plugins"]["claude/block-destructive-commands"]
        != lock["plugins"]["agent-plugins/block-destructive-commands"]
    ), "the same policy in two formats is two different artifacts"


def test_check_catches_a_tampered_plugin_directory(dist: Path) -> None:
    """The lockfile must fail when content changes, not only when the index does.

    A hand-edited guard script is exactly what the generated-only invariant exists to
    catch, and the index would not notice it: the manifest it reads is unchanged.
    """
    marketplace_main(["build", "--dist", str(dist)])
    assert marketplace_main(["build", "--dist", str(dist), "--check"]) == 0

    guard = dist / "claude" / "block-destructive-commands" / "scripts" / "block-destructive-commands.sh"
    guard.write_text("#!/usr/bin/env bash" + chr(10) + "exit 0  # tampered" + chr(10), encoding="utf-8")
    assert marketplace_main(["build", "--dist", str(dist), "--check"]) == 1
