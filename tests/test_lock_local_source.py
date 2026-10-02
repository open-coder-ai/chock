"""A local pack has one spelling in chock.lock, whichever of `add` and `sync` wrote it last."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from chock.lock import build_lock, verify_lock, write_lock
from chock.scaffold.add import add, record_provenance

FRAMEWORK_ROOT = Path(__file__).resolve().parents[1]
PACK = "protect-main-branch"
pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git required")


def _seed_catalog(root: Path) -> None:
    (root / "base").mkdir(parents=True)
    shutil.copytree(FRAMEWORK_ROOT / ".agents" / "policies" / PACK, root / "base" / PACK)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    r = tmp_path / "repo"
    (r / ".agents" / "policies").mkdir(parents=True)
    subprocess.run(["git", "init", "--quiet", "."], cwd=r, check=True, capture_output=True)
    return r


def _sync(repo: Path) -> str:
    write_lock(build_lock(repo), repo)
    return (repo / "chock.lock").read_text(encoding="utf-8")


def _entry(repo: Path) -> dict:
    return next(p for p in json.loads((repo / "chock.lock").read_text())["packs"] if p["id"] == PACK)


def _add_from_catalog(repo: Path, source: str, ref: str | None = None) -> None:
    write_lock(build_lock(repo), repo)
    added = add(repo, PACK, source, ref, force=False)
    write_lock(build_lock(repo), repo)
    record_provenance(repo, PACK, source, ref, added)


def test_add_from_the_repo_itself_then_sync_is_byte_stable(repo: Path) -> None:
    _seed_catalog(repo)
    _add_from_catalog(repo, str(repo))
    after_add = (repo / "chock.lock").read_text(encoding="utf-8")

    first, second = _sync(repo), _sync(repo)

    assert first == after_add == second
    assert _entry(repo)["source"] == "local"
    assert "source_commit" not in _entry(repo)


def test_dot_is_the_same_local_source(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _seed_catalog(repo)
    monkeypatch.chdir(repo)
    _add_from_catalog(repo, ".")
    assert _entry(repo)["source"] == "local"
    assert "source_commit" not in _entry(repo)


def test_an_old_spelling_converges_after_one_sync(repo: Path) -> None:
    shutil.copytree(FRAMEWORK_ROOT / ".agents" / "policies" / PACK, repo / ".agents" / "policies" / PACK)
    canonical = _sync(repo)
    lock = json.loads(canonical)
    lock["packs"][0].update({"source": ".", "source_commit": None})
    (repo / "chock.lock").write_text(json.dumps(lock, indent=2) + "\n", encoding="utf-8")

    assert _sync(repo) == canonical
    assert _sync(repo) == canonical
    assert verify_lock(repo) == (True, [])


def test_catalog_provenance_survives_sync_while_the_pack_is_unedited(repo: Path, tmp_path: Path) -> None:
    catalog = tmp_path / "catalog"
    _seed_catalog(catalog)
    for args in (
        ["git", "init", "--quiet", "-b", "main", "."],
        ["git", "config", "user.email", "c@example.invalid"],
        ["git", "config", "user.name", "Catalog"],
        ["git", "add", "-A"],
        ["git", "commit", "--quiet", "-m", "catalog"],
    ):
        subprocess.run(args, cwd=catalog, check=True, capture_output=True)
    _add_from_catalog(repo, str(catalog), "main")
    recorded = _entry(repo)
    assert recorded["source"] == str(catalog)
    assert recorded["source_commit"]

    assert _sync(repo) == _sync(repo)
    assert _entry(repo) == recorded
    assert verify_lock(repo) == (True, [])


def test_an_edited_catalog_pack_is_local_again(repo: Path, tmp_path: Path) -> None:
    catalog = tmp_path / "catalog"
    _seed_catalog(catalog)
    _add_from_catalog(repo, str(catalog))
    (repo / ".agents" / "policies" / PACK / "edited.txt").write_text("mine\n", encoding="utf-8")

    _sync(repo)

    assert _entry(repo)["source"] == "local"
    assert "source_commit" not in _entry(repo)
