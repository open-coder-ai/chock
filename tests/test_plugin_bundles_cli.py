"""`chock plugin build` and `chock marketplace build` once the bundles.yaml route is retired (design 2.1b).

A bundle is a selection, built by `chock install --selection`; the plugin repos' per-policy output stays.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from bundle_fixtures import ADVISORY_ID, BUNDLE_ID, GATE_ID, GUARD_ID, bundle, make_members

from chock.plugin import cli as plugin_cli
from chock.plugin import marketplace

FORMATS = ("agent-plugins", "claude", "codex", "copilot", "cursor", "devin")
#: The record the retired route wrote beside the packages; nothing writes it now.
OLD_INDEX = "chock-bundles.json"


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A repo that still carries a bundles.yaml from before the route was retired."""
    members = make_members(tmp_path, with_advisory=True)
    (tmp_path / "bundles.yaml").write_text(yaml.safe_dump({"bundles": [bundle(members)]}), encoding="utf-8")
    return tmp_path


def _build(repo: Path, *extra: str) -> int:
    return plugin_cli.main(["build", "--repo", str(repo), "--format", "all", "--out-dir", str(repo / "dist"), *extra])


def test_every_format_gets_each_policy_and_a_bundles_file_is_not_read(repo: Path) -> None:
    assert _build(repo) == 0
    for fmt in FORMATS:
        for policy_id in (GATE_ID, GUARD_ID, ADVISORY_ID):
            assert (repo / "dist" / fmt / policy_id).is_dir(), (fmt, policy_id)
        assert not (repo / "dist" / fmt / BUNDLE_ID).exists(), fmt
    assert not (repo / "dist" / OLD_INDEX).exists()


def test_the_bundles_flag_is_gone(repo: Path) -> None:
    with pytest.raises(SystemExit) as exc:
        _build(repo, "--bundles", str(repo / "bundles.yaml"))
    assert exc.value.code == 2


def test_check_passes_after_build_and_sees_a_drifted_policy(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _build(repo)
    assert _build(repo, "--check") == 0
    (repo / "dist" / "codex" / GATE_ID / "hooks" / "hooks.json").write_text("{}\n", encoding="utf-8")
    assert _build(repo, "--check") == 1
    assert f"differs: {GATE_ID}/hooks/hooks.json" in capsys.readouterr().out


def test_a_bundle_built_by_the_retired_route_is_stale_and_removed(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _build(repo)
    old = repo / "dist" / "claude" / BUNDLE_ID / ".claude-plugin"
    old.mkdir(parents=True)
    (old / "plugin.json").write_text(json.dumps({"name": BUNDLE_ID, "dependencies": [GATE_ID]}), encoding="utf-8")
    assert _build(repo, "--check") == 1
    assert f"stale: claude/{BUNDLE_ID}" in capsys.readouterr().out
    assert _build(repo) == 0
    assert not (repo / "dist" / "claude" / BUNDLE_ID).exists()
    assert _build(repo, "--check") == 0


def test_a_policy_narrowed_build_packages_only_that_policy(repo: Path) -> None:
    assert _build(repo, "--policy", GATE_ID) == 0
    assert (repo / "dist" / "claude" / GATE_ID).is_dir()
    assert not (repo / "dist" / "claude" / GUARD_ID).exists()


def test_the_marketplace_index_and_catalog_page_list_policies_only(repo: Path) -> None:
    _build(repo)
    (repo / "dist" / OLD_INDEX).write_text(json.dumps({"bundles": [{"id": GATE_ID, "members": []}]}), encoding="utf-8")
    dist = str(repo / "dist")
    assert marketplace.main(["build", "--dist", dist, "--tree", "claude"]) == 0
    index = json.loads((repo / "dist" / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8"))
    names = [p["name"] for p in index["plugins"]]
    assert names == sorted(names) == sorted([GATE_ID, GUARD_ID, ADVISORY_ID])
    page = (repo / "dist" / "PLUGINS.md").read_text(encoding="utf-8")
    assert "## Bundles" not in page
    assert f"| [`{GATE_ID}`]" in page
    assert marketplace.main(["build", "--dist", dist, "--tree", "claude", "--check"]) == 0
