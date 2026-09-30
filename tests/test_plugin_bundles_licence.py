"""A bundle's LICENSE is its own, and a bad bundles file fails the build instead of emptying it."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from bundle_fixtures import BUNDLE_ID, bundle, make_members

from chock.plugin import bundle_build
from chock.plugin import cli as plugin_cli
from chock.plugin.bundle_build import CLIENTS, MERGED, bundle_files
from chock.plugin.listing import LICENSE_REL

FORMATS = ["claude", "agent-plugins", *sorted(n for n, c in CLIENTS.items() if c.route == MERGED)]


def _members(tmp_path: Path, *provenances: dict) -> list:
    members = make_members(tmp_path)
    for member, provenance in zip(members, provenances):
        member.manifest["provenance"] = provenance
    return members


@pytest.mark.parametrize("fmt", FORMATS)
def test_members_from_different_years_share_one_notice_dated_from_the_oldest(tmp_path: Path, fmt: str) -> None:
    members = _members(
        tmp_path,
        {"author": "t", "license": "Apache-2.0", "created_at": "2025-03-01"},
        {"author": "t", "license": "Apache-2.0", "created_at": "2026-01-01"},
    )
    files = bundle_files(fmt, bundle(members), members, tmp_path)
    assert "2025" in files[LICENSE_REL] and "2026" not in files[LICENSE_REL]


@pytest.mark.parametrize("fmt", FORMATS)
def test_members_under_different_licences_ship_no_licence_for_the_bundle(tmp_path: Path, fmt: str) -> None:
    members = _members(
        tmp_path,
        {"author": "t", "license": "Apache-2.0", "created_at": "2026-01-01"},
        {"author": "t", "license": "MIT", "created_at": "2026-01-01"},
    )
    assert LICENSE_REL not in bundle_files(fmt, bundle(members), members, tmp_path)


def _build(repo: Path, *extra: str) -> int:
    return plugin_cli.main(["build", "--repo", str(repo), "--format", "codex", "--out-dir", str(repo / "dist"), *extra])


def test_a_named_bundles_file_that_is_missing_fails_and_keeps_what_was_built(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    members = make_members(tmp_path)
    (tmp_path / "bundles.yaml").write_text(yaml.safe_dump({"bundles": [bundle(members)]}), encoding="utf-8")
    assert _build(tmp_path) == 0
    assert _build(tmp_path, "--bundles", str(tmp_path / "missing.yaml")) == 2
    assert "no such bundles file" in capsys.readouterr().err
    assert (tmp_path / "dist" / "codex" / BUNDLE_ID).is_dir()
    assert _build(tmp_path, "--bundles", str(tmp_path / "bundles.yaml")) == 0


def test_a_merge_collision_is_reported_not_raised(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    members = make_members(tmp_path)
    (tmp_path / "bundles.yaml").write_text(yaml.safe_dump({"bundles": [bundle(members)]}), encoding="utf-8")

    def collide(*_args: object) -> None:
        bundle_build._place({Path("x"): "a"}, Path("x"), "b")

    monkeypatch.setattr(bundle_build, "merged_files", collide)
    assert _build(tmp_path) == 2
    assert "different bytes to x" in capsys.readouterr().err
