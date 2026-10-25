"""A catalog's linked area or pack directory never lets `chock add` copy files from outside the catalog."""

from __future__ import annotations

from pathlib import Path

import pytest

from chock.scaffold.add import IntegrityError, locate, verified_pack


def _outside(tmp_path: Path) -> Path:
    elsewhere = tmp_path / "elsewhere"
    (elsewhere / "evil-skill").mkdir(parents=True)
    (elsewhere / "evil-skill" / "SKILL.md").write_text("---\nname: evil-skill\n---\n", encoding="utf-8")
    return elsewhere


def test_a_linked_area_directory_is_not_followed(tmp_path: Path) -> None:
    catalog = tmp_path / "catalog"
    catalog.mkdir()
    (catalog / "skills").symlink_to(_outside(tmp_path), target_is_directory=True)

    with pytest.raises(FileNotFoundError):
        locate(catalog, "evil-skill")


def test_a_linked_pack_directory_is_not_followed(tmp_path: Path) -> None:
    catalog = tmp_path / "catalog"
    (catalog / "skills").mkdir(parents=True)
    (catalog / "skills" / "evil-skill").symlink_to(_outside(tmp_path) / "evil-skill", target_is_directory=True)

    with pytest.raises(FileNotFoundError):
        locate(catalog, "evil-skill")


def test_verified_pack_refuses_a_linked_pack_directory(tmp_path: Path) -> None:
    catalog = tmp_path / "catalog"
    (catalog / "skills").mkdir(parents=True)
    (catalog / "skills" / "evil-skill").symlink_to(_outside(tmp_path) / "evil-skill", target_is_directory=True)

    with pytest.raises((FileNotFoundError, IntegrityError)):
        verified_pack(catalog, "evil-skill", None)


def test_an_ordinary_pack_is_still_found(tmp_path: Path) -> None:
    catalog = tmp_path / "catalog"
    (catalog / "skills" / "good-skill").mkdir(parents=True)
    (catalog / "skills" / "good-skill" / "SKILL.md").write_text("---\nname: good-skill\n---\n", encoding="utf-8")

    src, _ = locate(catalog, "good-skill")

    assert src == catalog / "skills" / "good-skill"
