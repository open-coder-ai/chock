"""Manifest filename resolution tests."""

from pathlib import Path

import yaml

from chock.manifest import (
    CANONICAL_MANIFEST,
    load_manifest,
    load_manifest_file,
    resolve_manifest_path,
)


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_resolve_canonical(tmp_path: Path) -> None:
    _write(tmp_path / CANONICAL_MANIFEST, "id: test")
    resolved = resolve_manifest_path(tmp_path)
    assert resolved is not None
    assert resolved.name == CANONICAL_MANIFEST


def test_resolve_missing_returns_none(tmp_path: Path) -> None:
    assert resolve_manifest_path(tmp_path) is None
    assert load_manifest(tmp_path) is None


def test_load_empty_manifest(tmp_path: Path) -> None:
    _write(tmp_path / CANONICAL_MANIFEST, "")
    result = load_manifest(tmp_path)
    assert result is not None
    data, path = result
    assert data == {}
    assert path == tmp_path / CANONICAL_MANIFEST


def test_load_malformed_yaml_raises(tmp_path: Path) -> None:
    _write(tmp_path / CANONICAL_MANIFEST, "not valid: [")
    try:
        load_manifest(tmp_path)
        raise AssertionError("expected yaml.YAMLError")
    except yaml.YAMLError:
        pass


def test_load_manifest_file_defaults_propagation_for_block(tmp_path: Path) -> None:
    manifest = tmp_path / CANONICAL_MANIFEST
    _write(manifest, "id: x\nartifact: rule\nenforcement: block\nversion: 0.1.0\nname: X\ndescription: d")
    data = load_manifest_file(manifest)
    assert data["propagation"] == "inherit"


def test_load_manifest_and_file_agree_on_propagation_default(tmp_path: Path) -> None:
    manifest = tmp_path / CANONICAL_MANIFEST
    _write(manifest, "id: x\nartifact: rule\nenforcement: verify\nversion: 0.1.0\nname: X\ndescription: d")
    from_file = load_manifest_file(manifest)
    from_dir, _ = load_manifest(tmp_path)
    assert from_dir["propagation"] == from_file["propagation"] == "inherit"
