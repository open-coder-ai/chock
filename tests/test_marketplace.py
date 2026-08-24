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

from chock.plugin.cli import FORMATS
from chock.plugin.cli import main as plugin_main
from chock.plugin.marketplace import CATALOG_PAGE, DESCRIPTION, INDEX_PATHS, LOCKFILE_NAME
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
    # Derived from FORMATS, never enumerated by hand: an enumerated list is how a newly
    # added format silently escapes the lockfile while the check still reads as "covers
    # everything" -- the same under-coverage the catalog's trees.py exists to prevent.
    expected = {f"{fmt}/{manifest['id']}" for fmt in FORMATS for manifest in MANIFESTS}
    assert set(lock["plugins"]) == expected, "every tree is covered, not just the one the index points at"
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


def test_catalog_page_is_generated_not_typed(dist: Path) -> None:
    """A page that counts its own contents goes stale the moment a policy is added.

    A wrong count in the first thing a user reads is the same class of defect as a wrong
    coverage claim, so the page is generated rather than remembered. It is a file of its own
    because the repository's rules put README.md off limits to tooling.
    """
    marketplace_main(["build", "--dist", str(dist)])
    body = (dist / CATALOG_PAGE).read_text(encoding="utf-8")

    assert "2 policies are published here: 1 enforce in this client, 1 are advisory." in body
    assert "[`block-destructive-commands`](" in body, "each name links to its catalog page"
    assert "chock-catalog/blob/main/docs/block-destructive-commands/README.md" in body
    assert "| 0.0.2 | enforces |" in body
    assert "| 0.0.1 | advisory |" in body
    assert "friends before they run" in body, "a scannable summary, not the full text"
    assert "fails open" in body, "the caveat travels with the count"


def test_check_catches_a_stale_catalog_page(dist: Path) -> None:
    marketplace_main(["build", "--dist", str(dist)])
    assert marketplace_main(["build", "--dist", str(dist), "--check"]) == 0

    page = dist / CATALOG_PAGE
    page.write_text(page.read_text(encoding="utf-8").replace("2 policies", "99 policies"), encoding="utf-8")
    assert marketplace_main(["build", "--dist", str(dist), "--check"]) == 1


def test_readme_is_never_touched(dist: Path) -> None:
    """The repository's rules put README.md off limits to tooling; honour it in both modes.

    Checked through `stat()` rather than by reading the file, because a test that opened
    README.md to prove nothing opens README.md would be the very thing it is asserting
    against. Size and modification time change on any rewrite, including one that produced
    identical bytes.
    """
    readme = dist / "README.md"
    readme.write_bytes(b"# hand written" + bytes([10]))
    before = readme.stat()

    marketplace_main(["build", "--dist", str(dist)])
    after_build = readme.stat()
    assert (after_build.st_size, after_build.st_mtime_ns) == (before.st_size, before.st_mtime_ns)

    assert marketplace_main(["build", "--dist", str(dist), "--check"]) == 0
    after_check = readme.stat()
    assert (after_check.st_size, after_check.st_mtime_ns) == (before.st_size, before.st_mtime_ns)


def test_cursor_tree_gets_cursors_own_index_schema(dist: Path) -> None:
    """`--tree cursor` writes `.cursor-plugin/marketplace.json` in Cursor's schema.

    Copied from cursor/plugins and cursor/plugin-template verbatim: description under
    `metadata`, name-only owner, entries of exactly {name, source, description} with
    sources pointing into the cursor tree. Cursor never reads the Claude index paths.
    """
    assert marketplace_main(["build", "--dist", str(dist), "--name", "chock-cursor", "--tree", "cursor"]) == 0
    index = json.loads((dist / ".cursor-plugin" / "marketplace.json").read_text(encoding="utf-8"))

    assert index["name"] == "chock-cursor"
    assert index["owner"] == {"name": "open-coder-ai"}
    assert index["metadata"]["description"]
    assert "description" not in index, "cursor puts the description under metadata"
    for entry in index["plugins"]:
        assert set(entry) == {"name", "source", "description"}
        assert entry["source"].startswith("./cursor/")


def test_codex_tree_reuses_the_witnessed_legacy_index(dist: Path) -> None:
    """`--tree codex` writes the legacy Claude-shape index with codex sources.

    Codex reads `.claude-plugin/marketplace.json` from git marketplaces -- witnessed on a
    real install (this machine's Codex pulled chock from exactly that file), not inferred
    from documentation -- so the codex repo speaks the index dialect Codex is known to
    consume, pointing at the `.codex-plugin` packages.
    """
    assert marketplace_main(["build", "--dist", str(dist), "--name", "chock-codex", "--tree", "codex"]) == 0
    index = json.loads((dist / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8"))

    assert index["description"], "legacy shape keeps the top-level description"
    sources = [entry["source"] for entry in index["plugins"]]
    assert sources and all(s.startswith("./codex/") for s in sources)
    # Only the legacy path is written for codex: the Copilot mirror belongs to the
    # claude tree's clients.
    assert not (dist / ".github" / "plugin" / "marketplace.json").exists()
