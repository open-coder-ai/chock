"""A bundle's LICENSE is its own: one notice when every member shares a licence and holder, else none."""

from __future__ import annotations

from pathlib import Path

import pytest
from bundle_fixtures import bundle, make_members

from chock.plugin.bundle_build import CLIENTS, merged_files
from chock.plugin.listing import LICENSE_REL

FORMATS = sorted(CLIENTS)


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
    files = merged_files(fmt, bundle(members), members, tmp_path)
    assert "2025" in files[LICENSE_REL] and "2026" not in files[LICENSE_REL]


@pytest.mark.parametrize("fmt", FORMATS)
def test_members_under_different_licences_ship_no_licence_for_the_bundle(tmp_path: Path, fmt: str) -> None:
    members = _members(
        tmp_path,
        {"author": "t", "license": "Apache-2.0", "created_at": "2026-01-01"},
        {"author": "t", "license": "MIT", "created_at": "2026-01-01"},
    )
    assert LICENSE_REL not in merged_files(fmt, bundle(members), members, tmp_path)
