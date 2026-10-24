"""A pack hash identifies one file set: moving bytes across a file boundary changes it."""

from __future__ import annotations

import hashlib
from pathlib import Path

from chock.lock import LOCKFILE_VERSION, build_lock, compute_pack_hash, pack_hash_matches, verify_lock


def _pack(root: Path, files: dict[str, bytes]) -> Path:
    for name, data in files.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_bytes(data)
    return root


def _legacy(pack: Path) -> str:
    h = hashlib.sha256()
    for path in sorted(p for p in pack.rglob("*") if p.is_file()):
        h.update(path.relative_to(pack).as_posix().encode())
        h.update(b"\0")
        h.update(path.read_bytes())
        h.update(b"\0")
    return h.hexdigest()


def test_a_file_boundary_cannot_be_moved_inside_the_stream(tmp_path: Path) -> None:
    one = _pack(tmp_path / "one", {"a": b"X\0b\0Y"})
    two = _pack(tmp_path / "two", {"a": b"X", "b": b"Y"})

    assert _legacy(one) == _legacy(two)
    assert compute_pack_hash(one) != compute_pack_hash(two)


def test_the_hash_is_stable_for_the_same_files(tmp_path: Path) -> None:
    one = _pack(tmp_path / "one", {"a": b"1", "d/b": b"2"})
    two = _pack(tmp_path / "two", {"d/b": b"2", "a": b"1"})

    assert compute_pack_hash(one) == compute_pack_hash(two)


def test_a_legacy_hash_still_matches_a_pack_without_nul_bytes(tmp_path: Path) -> None:
    pack = _pack(tmp_path / "p", {"a": b"text", "d/b": b"more"})

    assert pack_hash_matches(pack, _legacy(pack))
    assert pack_hash_matches(pack, compute_pack_hash(pack))
    assert not pack_hash_matches(pack, "0" * 64)


def test_a_legacy_hash_is_refused_for_a_pack_with_nul_bytes(tmp_path: Path) -> None:
    pack = _pack(tmp_path / "p", {"a": b"X\0b\0Y"})

    assert not pack_hash_matches(pack, _legacy(pack))


def test_a_version_1_lock_still_verifies_and_is_rewritten_as_version_2(tmp_path: Path) -> None:
    import json
    import subprocess

    pack = _pack(tmp_path / ".agents" / "policies" / "demo-rule", {"manifest.yaml": b"id: demo-rule\n"})
    subprocess.run(["git", "init", "--quiet", str(tmp_path)], check=True)
    lock = build_lock(tmp_path)
    lock["lockfile_version"] = "1"
    lock["packs"][0]["sha256"] = _legacy(pack)
    (tmp_path / "chock.lock").write_text(json.dumps(lock), encoding="utf-8")

    ok, failures = verify_lock(tmp_path)

    assert [f for f in failures if "demo-rule" in f] == []
    assert build_lock(tmp_path)["lockfile_version"] == LOCKFILE_VERSION == "2"
