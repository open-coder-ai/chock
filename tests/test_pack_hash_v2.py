"""Pack hash v2: golden vectors, v1 accepted only where unambiguous, every comparison site, lock migration."""

from __future__ import annotations

import base64
import json
import re
import shutil
from pathlib import Path
from typing import Any

import pytest
from conftest import baseline_policy
from local_fixtures import MY, make_mine, only_local

from chock import lock as lock_mod
from chock.install import local as local_mod
from chock.lock import _hash_v1, _read_pack, build_lock, compute_pack_hash, pack_hash_matches, verify_lock, write_lock
from chock.plugin import marketplace_core
from chock.scaffold import add as add_mod
from chock.scaffold.add import IntegrityError, verified_pack

VECTORS = Path(__file__).parent / "fixtures" / "pack_hash_v2_vectors.json"
POLICY = "protect-main-branch"
SOURCE = "https://example.invalid/catalog"
COMMIT = "a" * 40


def _vectors() -> list[dict[str, Any]]:
    return json.loads(VECTORS.read_text(encoding="utf-8"))["vectors"]


def _write(pack: Path, files: list[tuple[str, bytes]]) -> Path:
    pack.mkdir(parents=True, exist_ok=True)
    for rel, data in files:
        dest = pack / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
    return pack


def v1_of(pack: Path) -> str:
    return _hash_v1(_read_pack(pack))


def _pack(tmp_path: Path, nul: bool = False) -> Path:
    return _write(tmp_path / "pack", [("a.txt", b"a\n"), ("b/c.bin", b"x\0y" if nul else b"xy")])


@pytest.mark.parametrize("vector", _vectors(), ids=lambda v: v["name"])
def test_golden_vectors(vector: dict[str, Any], tmp_path: Path) -> None:
    files = [(f["path"], base64.b64decode(f["content_b64"])) for f in vector["files"]]
    pack = _write(tmp_path / "pack", files)
    assert compute_pack_hash(pack) == vector["v2"]
    assert v1_of(pack) == vector["v1"]


def test_nul_pair_collides_under_v1_not_v2(tmp_path: Path) -> None:
    by_name = {v["name"]: v for v in _vectors()}
    split, joined = by_name["nul-split"], by_name["nul-joined"]
    assert split["v1"] == joined["v1"], "the vector pair must collide under v1"
    assert split["v2"] != joined["v2"]
    a = _write(tmp_path / "a", [("a", b"1"), ("b", b"2")])
    b = _write(tmp_path / "b", [("a", b"1\0b\x002")])
    assert v1_of(a) == v1_of(b)
    assert compute_pack_hash(a) != compute_pack_hash(b)
    assert pack_hash_matches(a, v1_of(b)), "no NUL in `a`: the shared v1 hash is unambiguous there"
    assert not pack_hash_matches(b, v1_of(a)), "a NUL pack never matches a v1 hash"


def test_v2_is_always_accepted_and_v1_only_without_a_nul(tmp_path: Path) -> None:
    clean = _pack(tmp_path)
    assert pack_hash_matches(clean, compute_pack_hash(clean))
    assert pack_hash_matches(clean, v1_of(clean))
    dirty = _pack(tmp_path / "d", nul=True)
    assert pack_hash_matches(dirty, compute_pack_hash(dirty))
    assert not pack_hash_matches(dirty, v1_of(dirty))


@pytest.mark.parametrize("bad", [None, "", "0" * 64, 7])
def test_other_values_never_match(tmp_path: Path, bad: object) -> None:
    assert not pack_hash_matches(_pack(tmp_path), bad)


def test_the_v2_hash_is_not_the_v1_hash(tmp_path: Path) -> None:
    pack = _pack(tmp_path)
    assert compute_pack_hash(pack) != v1_of(pack)


def test_every_site_calls_pack_hash_matches() -> None:
    """No source file compares a pack hash with ==/!=; the comparison lives in `pack_hash_matches` alone."""
    src = Path(lock_mod.__file__).parent
    pattern = re.compile(r"(compute_pack_hash|compute_artifacts_hash)\([^)]*\)\s*(==|!=)|(==|!=)\s*compute_pack_hash\(")
    hits = [str(p) for p in src.rglob("*.py") if pattern.search(p.read_text(encoding="utf-8"))]
    assert hits == []


@pytest.fixture
def spy(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    seen: list[str] = []
    for mod in (lock_mod, add_mod, local_mod, marketplace_core):
        real = mod.pack_hash_matches

        def wrapped(pack_dir: Path, expected: object, _real: Any = real, _name: str = mod.__name__) -> bool:
            seen.append(_name)
            return _real(pack_dir, expected)

        monkeypatch.setattr(mod, "pack_hash_matches", wrapped)
    return seen


def _catalog(tmp_path: Path, nul: bool) -> tuple[Path, str]:
    cat = tmp_path / "cat"
    shutil.copytree(baseline_policy(POLICY), cat / "base" / POLICY)
    if nul:
        (cat / "base" / POLICY / "blob.bin").write_bytes(b"a\0b")
    return cat, v1_of(cat / "base" / POLICY)


def test_verify_sha_and_selection_pins(tmp_path: Path, spy: list[str]) -> None:
    cat, old = _catalog(tmp_path, nul=False)
    _src, _area, digest = verified_pack(cat, POLICY, old)
    assert digest == compute_pack_hash(cat / "base" / POLICY), "the recorded hash is v2 even when a v1 pin matched"
    assert spy == [add_mod.__name__]
    verified_pack(cat, POLICY, digest)


def test_verify_sha_refuses_v1_when_a_file_holds_a_nul(tmp_path: Path) -> None:
    cat, old = _catalog(tmp_path, nul=True)
    with pytest.raises(IntegrityError, match="expected sha256"):
        verified_pack(cat, POLICY, old)
    verified_pack(cat, POLICY, compute_pack_hash(cat / "base" / POLICY))


def test_resolve_members_goes_through_verified_pack(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from chock.install import resolve

    assert resolve.verified_pack is add_mod.verified_pack


def test_local_entry_pin_and_trust_local(tmp_path: Path, spy: list[str]) -> None:
    folder = make_mine(tmp_path)
    old = v1_of(folder / ".agents" / "policies" / MY)
    found = local_mod.snapshot(only_local(sha256=old), folder, tmp_path / "snap")
    assert spy.count(local_mod.__name__) == 1
    item = found[0]
    assert item.sha256 == compute_pack_hash(item.snapshot)
    local_mod._check_given([item], {MY: old})
    assert spy.count(local_mod.__name__) == 2
    out = local_mod.confirm([item], local_mod.Trust(accepted={MY: old}, given={}, interactive=False))
    assert spy.count(local_mod.__name__) == 3
    assert out == {MY: item.sha256}, "the marker is rewritten with the v2 hash"


def test_local_refuses_v1_when_a_file_holds_a_nul(tmp_path: Path) -> None:
    folder = make_mine(tmp_path)
    pack = folder / ".agents" / "policies" / MY
    (pack / "blob.bin").write_bytes(b"a\0b")
    old = v1_of(pack)
    with pytest.raises(IntegrityError, match="pins sha256"):
        local_mod.snapshot(only_local(sha256=old), folder, tmp_path / "snap")
    item = local_mod.snapshot(only_local(), folder, tmp_path / "snap2")[0]
    with pytest.raises(IntegrityError, match="--trust-local gives"):
        local_mod._check_given([item], {MY: old})
    with pytest.raises(IntegrityError, match="needs your confirmation"):
        local_mod.confirm([item], local_mod.Trust(accepted={MY: old}, given={}, interactive=False), out=None)


def _dist(tmp_path: Path, nul: bool) -> Path:
    dist = tmp_path / "dist"
    _write(dist / "claude" / "p", [("plugin.json", b"{}"), ("blob", b"a\0b" if nul else b"ab")])
    return dist


def _old_market_lock(dist: Path) -> None:
    plugins = {"claude/p": v1_of(dist / "claude" / "p")}
    text = json.dumps({"lockfile_version": 1, "plugins": plugins}, indent=2, sort_keys=True) + "\n"
    (dist / marketplace_core.LOCKFILE_NAME).write_text(text, encoding="utf-8")


def test_marketplace_lock_v2_written_and_v1_accepted_when_unambiguous(tmp_path: Path, spy: list[str]) -> None:
    dist = _dist(tmp_path, nul=False)
    assert marketplace_core.build_lock(dist)["lockfile_version"] == 2
    _old_market_lock(dist)
    assert marketplace_core.lock_differences(dist) == []
    assert spy == [marketplace_core.__name__]
    (dist / marketplace_core.LOCKFILE_NAME).write_text(
        json.dumps(marketplace_core.build_lock(dist), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    assert marketplace_core.lock_differences(dist) == []


def test_marketplace_lock_v1_refused_with_a_nul(tmp_path: Path) -> None:
    dist = _dist(tmp_path, nul=True)
    _old_market_lock(dist)
    assert marketplace_core.lock_differences(dist) == [f"differs: {marketplace_core.LOCKFILE_NAME}"]


def _repo_with_v1_lock(tmp_path: Path, nul: bool = False) -> Path:
    pack = tmp_path / ".agents" / "policies" / POLICY
    pack.parent.mkdir(parents=True)
    shutil.copytree(baseline_policy(POLICY), pack)
    if nul:
        (pack / "blob.bin").write_bytes(b"a\0b")
    entry = {
        "id": POLICY,
        "version": "0.0.1",
        "managed": False,
        "sha256": v1_of(pack),
        "source": SOURCE,
        "source_commit": COMMIT,
    }
    write_lock({"lockfile_version": "1", "engine": ">=0.1,<0.2", "packs": [entry]}, tmp_path)
    return tmp_path


def test_a_v1_lock_verifies_and_migrates_keeping_provenance(tmp_path: Path, spy: list[str]) -> None:
    repo = _repo_with_v1_lock(tmp_path)
    ok, failures = verify_lock(repo)
    assert ok, failures
    assert spy.count(lock_mod.__name__) >= 1
    new = build_lock(repo)
    entry = new["packs"][0]
    assert new["lockfile_version"] == "2"
    assert entry["sha256"] == compute_pack_hash(repo / ".agents" / "policies" / POLICY)
    assert (entry["source"], entry["source_commit"]) == (SOURCE, COMMIT)
    write_lock(new, repo)
    assert verify_lock(repo) == (True, [])


def test_a_v1_lock_with_a_nul_fails_verify_and_drops_provenance(tmp_path: Path) -> None:
    repo = _repo_with_v1_lock(tmp_path, nul=True)
    ok, failures = verify_lock(repo)
    assert not ok and any("hash mismatch" in f for f in failures), failures
    entry = build_lock(repo)["packs"][0]
    assert entry["source"] == "local" and "source_commit" not in entry


def test_artifacts_hash_goes_through_pack_hash_matches(tmp_path: Path, spy: list[str]) -> None:
    from chock.scaffold.recompile import recompile

    repo = _repo_with_v1_lock(tmp_path)
    recompile(repo, ["claude"], skip_hooks=True)
    write_lock(build_lock(repo), repo)
    spy.clear()
    assert verify_lock(repo)[0]
    assert spy.count(lock_mod.__name__) >= 2, "the pack hash and the compiled-artifacts hash"


def test_marketplace_v1_lock_with_foreign_keys_is_refused_unread(tmp_path: Path, spy: list[str]) -> None:
    dist = _dist(tmp_path, nul=False)
    (tmp_path / "x").mkdir()
    text = json.dumps({"lockfile_version": 1, "plugins": {"../x": "0" * 64}}, indent=2, sort_keys=True) + "\n"
    (dist / marketplace_core.LOCKFILE_NAME).write_text(text, encoding="utf-8")
    assert marketplace_core.lock_differences(dist) == [f"differs: {marketplace_core.LOCKFILE_NAME}"]
    assert spy == [], "no path from the lock was hashed"
