"""`chock plugin build` and `chock marketplace build` over a repo with a bundles file."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from bundle_fixtures import ADVISORY_ID, BUNDLE_ID, GATE_ID, GUARD_ID, bundle, make_members

from chock.plugin import cli as plugin_cli
from chock.plugin import marketplace
from chock.plugin.bundle_index import BUNDLES_INDEX


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    members = make_members(tmp_path, with_advisory=True)
    (tmp_path / "bundles.yaml").write_text(yaml.safe_dump({"bundles": [bundle(members)]}), encoding="utf-8")
    return tmp_path


def _build(repo: Path, *extra: str) -> int:
    return plugin_cli.main(["build", "--repo", str(repo), "--format", "all", "--out-dir", str(repo / "dist"), *extra])


def test_every_format_gets_the_bundle_beside_its_policies(repo: Path) -> None:
    assert _build(repo) == 0
    for fmt in ("agent-plugins", "claude", "codex", "copilot", "cursor", "devin"):
        assert (repo / "dist" / fmt / BUNDLE_ID).is_dir(), fmt
        assert (repo / "dist" / fmt / GATE_ID).is_dir(), fmt
    record = json.loads((repo / "dist" / BUNDLES_INDEX).read_text(encoding="utf-8"))
    assert record == {"bundles": [{"id": BUNDLE_ID, "members": [GATE_ID, GUARD_ID, ADVISORY_ID]}]}


def test_check_passes_after_build_and_sees_a_drifted_bundle(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _build(repo)
    assert _build(repo, "--check") == 0
    (repo / "dist" / "codex" / BUNDLE_ID / "hooks" / "hooks.json").write_text("{}\n", encoding="utf-8")
    assert _build(repo, "--check") == 1
    assert f"differs: {BUNDLE_ID}/hooks/hooks.json" in capsys.readouterr().out


def test_check_sees_a_missing_bundle_index(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _build(repo)
    (repo / "dist" / BUNDLES_INDEX).unlink()
    assert _build(repo, "--check") == 1
    assert f"missing: {BUNDLES_INDEX}" in capsys.readouterr().out


def test_a_bundle_left_out_of_the_file_is_removed_on_the_next_build(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _build(repo)
    (repo / "bundles.yaml").unlink()
    assert _build(repo, "--check") == 1
    assert f"stale: claude/{BUNDLE_ID}" in capsys.readouterr().out
    assert _build(repo) == 0
    assert not (repo / "dist" / "claude" / BUNDLE_ID).exists()
    assert not (repo / "dist" / BUNDLES_INDEX).exists()
    assert _build(repo, "--check") == 0


def test_an_unknown_member_fails_the_build_and_names_it(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    doc = yaml.safe_load((repo / "bundles.yaml").read_text(encoding="utf-8"))
    doc["bundles"][0]["members"].append("no-such-policy")
    (repo / "bundles.yaml").write_text(yaml.safe_dump(doc), encoding="utf-8")
    assert _build(repo) == 2
    assert "no-such-policy" in capsys.readouterr().err


def test_a_policy_narrowed_build_leaves_bundles_alone(repo: Path) -> None:
    assert _build(repo, "--policy", GATE_ID) == 0
    assert not (repo / "dist" / "claude" / BUNDLE_ID).exists()


def test_the_marketplace_index_and_catalog_page_list_bundles_first(repo: Path) -> None:
    _build(repo)
    dist = str(repo / "dist")
    assert marketplace.main(["build", "--dist", dist, "--tree", "claude"]) == 0
    index = json.loads((repo / "dist" / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8"))
    assert index["plugins"][0]["name"] == BUNDLE_ID
    assert [p["name"] for p in index["plugins"][1:]] == sorted(p["name"] for p in index["plugins"][1:])
    page = (repo / "dist" / "PLUGINS.md").read_text(encoding="utf-8")
    assert page.index("## Bundles") < page.index("## Policies") < page.index(f"| [`{GATE_ID}`]")
    assert f"`{BUNDLE_ID}` | 0.1.0 | advisory (weakest member)" in page
    assert marketplace.main(["build", "--dist", dist, "--tree", "claude", "--check"]) == 0


def test_a_repo_without_bundles_builds_exactly_as_before(tmp_path: Path) -> None:
    make_members(tmp_path)
    assert (
        plugin_cli.main(["build", "--repo", str(tmp_path), "--format", "claude", "--out-dir", str(tmp_path / "d")]) == 0
    )
    assert not (tmp_path / "d" / BUNDLES_INDEX).exists()
    marketplace.main(["build", "--dist", str(tmp_path / "d"), "--tree", "claude"])
    assert "## Bundles" not in (tmp_path / "d" / "PLUGINS.md").read_text(encoding="utf-8")
