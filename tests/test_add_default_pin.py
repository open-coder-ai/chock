"""`chock add <id>` with no `--ref` takes the default catalog's release tag, never its moving branch."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from add_pin_support import ID, commit, make_remote
from add_pin_support import git as _git

from chock.lock import build_lock, write_lock
from chock.scaffold import add as add_mod

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git required")

FRAMEWORK_ROOT = Path(__file__).resolve().parents[1]
POLICY = "protect-main-branch"
VERSION = "9.8.7"
TAG = f"v{VERSION}"


@pytest.fixture
def catalog(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, str, str]:
    """A bare catalog standing in for the default one: (path, tagged commit, newer commit on main)."""
    work, _, _ = make_remote(tmp_path)
    shutil.copytree(FRAMEWORK_ROOT / ".agents" / "policies" / POLICY, work / "base" / POLICY)
    _git(work, "add", "-A")
    _git(work, "commit", "--quiet", "-m", "policy")
    tagged = _git(work, "rev-parse", "HEAD")
    _git(work, "tag", "-a", TAG, "-m", "release", tagged)
    newer = commit(work, "newer")
    bare = tmp_path / "catalog.git"
    _git(tmp_path, "clone", "--quiet", "--bare", str(work), str(bare))
    _git(bare, "config", "uploadpack.allowAnySHA1InWant", "true")
    monkeypatch.setattr(add_mod, "DEFAULT_CATALOG", bare.as_uri())
    monkeypatch.setattr(add_mod, "engine_version", VERSION)
    return bare, tagged, newer


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    r = tmp_path / "repo"
    r.mkdir()
    _git(r, "init", "--quiet", ".")
    monkeypatch.setattr(add_mod, "_agents_from_config", lambda _root: [])
    monkeypatch.setattr(add_mod, "recompile", lambda root, _agents, **_kw: write_lock(build_lock(root), root))
    return r


def _installed_body(repo: Path) -> str:
    return (repo / ".agents" / "skills" / ID / "SKILL.md").read_text(encoding="utf-8")


def _entry(repo: Path) -> dict:
    packs = json.loads((repo / "chock.lock").read_text(encoding="utf-8"))["packs"]
    return next(p for p in packs if p["id"] == POLICY)


def test_no_ref_takes_the_release_tag_and_records_it(catalog, repo: Path, capsys) -> None:
    _, tagged, newer = catalog
    assert add_mod.main([ID, "--repo", str(repo)]) == 0
    out = capsys.readouterr().out
    assert f"at {tagged} (tag {TAG})" in out
    assert f"the strong pin is --ref {tagged}, or --verify-sha" in out
    assert "unpinned" not in out
    assert "good" in _installed_body(repo)
    assert newer != tagged
    assert add_mod.main([POLICY, "--repo", str(repo)]) == 0
    entry = _entry(repo)
    assert entry["source_commit"] == tagged
    assert entry["source_ref"] == TAG


def test_a_missing_tag_fails_and_never_falls_back_to_the_branch(catalog, repo: Path, capsys, monkeypatch) -> None:
    monkeypatch.setattr(add_mod, "engine_version", "0.0.1.dev0")
    assert add_mod.main([ID, "--repo", str(repo)]) == 2
    err = capsys.readouterr().err.strip()
    assert len(err.splitlines()) == 1
    assert "no tag v0.0.1.dev0" in err
    assert "--ref <40-hex commit>" in err
    assert "--ref main" in err
    assert not (repo / ".agents").exists()


def test_an_explicit_ref_is_unchanged(catalog, repo: Path, capsys) -> None:
    _, _, newer = catalog
    assert add_mod.main([ID, "--repo", str(repo), "--ref", "main", "--skip-compile"]) == 0
    captured = capsys.readouterr()
    assert "can move" in captured.err
    assert f"at {newer}\n" in captured.out
    assert "newer" in _installed_body(repo)


def test_another_catalog_without_ref_takes_its_default_branch(catalog, repo: Path, tmp_path: Path, capsys) -> None:
    bare, _, newer = catalog
    local = tmp_path / "local-catalog"
    _git(tmp_path, "clone", "--quiet", str(bare), str(local))
    assert add_mod.main([ID, "--repo", str(repo), "--from", str(local), "--skip-compile"]) == 0
    out = capsys.readouterr().out
    assert f"at {newer}\n" in out
    assert "unpinned" in out
    assert "newer" in _installed_body(repo)


@pytest.mark.parametrize("suffix", ["", "/", ".git"])
def test_the_default_catalog_is_recognised_however_it_ends(suffix: str) -> None:
    assert add_mod.default_tag(add_mod.DEFAULT_CATALOG + suffix, None) == f"v{add_mod.engine_version}"
    assert add_mod.default_tag(add_mod.DEFAULT_CATALOG, "main") is None
    assert add_mod.default_tag("https://example.invalid/catalog", None) is None


def test_help_names_the_default(capsys) -> None:
    with pytest.raises(SystemExit):
        add_mod.main(["--help"])
    assert "v<chock version>" in " ".join(capsys.readouterr().out.split())
