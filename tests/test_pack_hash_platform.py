"""A pack hashes the same on every platform and every checkout: file order and line endings never move it."""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from chock.lock import compute_pack_hash
from chock.scaffold.add import add, verified_pack
from chock.scaffold.pin import fetch_catalog

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git required")

PACK = "demo"
FILES = {"Z.txt": b"z\n", "a.txt": b"a\n", "manifest.yaml": f"id: {PACK}\n".encode()}
CODE_POINT_ORDER = ("Z.txt", "a.txt", "manifest.yaml")
CASE_FOLDED_ORDER = ("a.txt", "manifest.yaml", "Z.txt")
PINNED_DIGEST = "0ee91daec41c3df916c05b5b6a01dd53999ca1d5cf192e39ad461db9ad1c4ed0"


def _digest(order: tuple[str, ...]) -> str:
    h = hashlib.sha256()
    for name in order:
        h.update(name.encode("utf-8") + b"\0" + FILES[name] + b"\0")
    return h.hexdigest()


def _write_pack(pack: Path, newline: bytes = b"\n") -> None:
    pack.mkdir(parents=True, exist_ok=True)
    for name, data in FILES.items():
        (pack / name).write_bytes(data.replace(b"\n", newline))


def _git(cwd: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", "-c", "user.email=t@example.invalid", "-c", "user.name=t", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )
    return done.stdout.strip()


def _catalog(root: Path) -> str:
    """A committed catalog holding `base/demo` with LF line endings: (HEAD)."""
    _write_pack(root / "base" / PACK)
    _git(root, "init", "--quiet", "-b", "main")
    _git(root, "add", "-A")
    _git(root, "commit", "--quiet", "-m", "catalog")
    return _git(root, "rev-parse", "HEAD")


def _crlf_working_tree(root: Path) -> None:
    """What a Windows checkout under core.autocrlf=true looks like: committed LF, working tree CRLF."""
    for path in (root / "base" / PACK).iterdir():
        path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))


def test_the_synthetic_pack_hashes_in_code_point_order(tmp_path: Path) -> None:
    """Windows sorts `Path` case-insensitively (a.txt before Z.txt); the hash follows code points everywhere."""
    _write_pack(tmp_path / PACK)
    assert _digest(CODE_POINT_ORDER) != _digest(CASE_FOLDED_ORDER)
    assert compute_pack_hash(tmp_path / PACK) == _digest(CODE_POINT_ORDER) == PINNED_DIGEST


def test_the_hash_does_not_follow_the_directory_walk(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write_pack(tmp_path / PACK)
    walked = sorted(Path.rglob(tmp_path / PACK, "*"), key=lambda p: p.name.lower(), reverse=True)
    monkeypatch.setattr(Path, "rglob", lambda _self, _pattern: iter(walked))
    assert compute_pack_hash(tmp_path / PACK) == PINNED_DIGEST


def test_a_crlf_working_tree_add_verifies_against_a_clone(tmp_path: Path) -> None:
    """The hash `chock add` records from a local checkout is the one a clone of that commit verifies."""
    catalog, head = tmp_path / "catalog", _catalog(tmp_path / "catalog")
    _crlf_working_tree(catalog)
    repo = tmp_path / "repo"
    (repo / ".agents" / "policies").mkdir(parents=True)

    added = add(repo, PACK, str(catalog), None, force=False)

    assert added.commit == head
    assert added.sha256 == PINNED_DIGEST
    assert (added.path / "a.txt").read_bytes() == b"a\n"
    cloned, commit = fetch_catalog(f"file://{catalog}", head, tmp_path / "clone")
    assert commit == head
    assert verified_pack(cloned, PACK, added.sha256)[2] == added.sha256


def test_a_local_checkout_is_read_at_head_not_its_working_tree(tmp_path: Path) -> None:
    catalog, head = tmp_path / "catalog", _catalog(tmp_path / "catalog")
    (catalog / "base" / PACK / "UNCOMMITTED.md").write_text("not committed\n", encoding="utf-8")

    fetched, commit = fetch_catalog(str(catalog), None, tmp_path / "fetched")

    assert commit == head
    assert not (fetched / "base" / PACK / "UNCOMMITTED.md").exists()
    assert compute_pack_hash(fetched / "base" / PACK) == PINNED_DIGEST


def test_a_catalog_below_the_checkout_root_is_read_at_head(tmp_path: Path) -> None:
    """`--from <repo>/catalog`: the prefix inside the checkout, not the whole repository, is the catalog."""
    _catalog(tmp_path)
    nested = tmp_path / "catalog"
    nested.mkdir()
    shutil.move(tmp_path / "base", nested / "base")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "--quiet", "-m", "nest")
    head = _git(tmp_path, "rev-parse", "HEAD")
    _crlf_working_tree(nested)

    fetched, commit = fetch_catalog(str(nested), None, tmp_path / "fetched")

    assert commit == head
    assert compute_pack_hash(fetched / "base" / PACK) == PINNED_DIGEST
    assert not (fetched / "catalog").exists()


def test_an_uncommitted_directory_in_a_checkout_is_copied_as_git_would_commit_it(tmp_path: Path) -> None:
    """Nothing at HEAD to clone: the working tree is the only source, so it is read with LF like a commit."""
    _catalog(tmp_path / "catalog")
    untracked = tmp_path / "catalog" / "untracked"
    _write_pack(untracked / "base" / PACK, newline=b"\r\n")

    fetched, commit = fetch_catalog(str(untracked), None, tmp_path / "fetched")

    assert commit is None
    assert compute_pack_hash(fetched / "base" / PACK) == PINNED_DIGEST


def test_a_plain_directory_is_normalised_to_lf_but_binaries_are_left_alone(tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    _write_pack(plain / "base" / PACK, newline=b"\r\n")
    binary = b"\x89PNG\r\n\x1a\n\0\0\r\n"
    (plain / "base" / PACK / "logo.png").write_bytes(binary)

    fetched, commit = fetch_catalog(str(plain), None, tmp_path / "fetched")

    assert commit is None
    assert (fetched / "base" / PACK / "a.txt").read_bytes() == b"a\n"
    assert (fetched / "base" / PACK / "logo.png").read_bytes() == binary
    assert (plain / "base" / PACK / "a.txt").read_bytes() == b"a\r\n", "the source directory is not rewritten"


def test_a_plain_directory_keeps_its_symlinks_for_the_pack_check(tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    _write_pack(plain / "base" / PACK)
    try:
        os.symlink(plain / "base" / PACK / "a.txt", plain / "base" / PACK / "leak")
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not available here")

    fetched, _commit = fetch_catalog(str(plain), None, tmp_path / "fetched")

    assert (fetched / "base" / PACK / "leak").is_symlink()


def test_normalising_never_follows_a_symlink_out_of_the_catalog(tmp_path: Path) -> None:
    """A planted link to a directory outside the catalog must not get that directory's files rewritten."""
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "notes.txt").write_bytes(b"theirs\r\n")
    plain = tmp_path / "plain"
    _write_pack(plain / "base" / PACK)
    try:
        os.symlink(outside, plain / "base" / PACK / "tree", target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not available here")

    fetched, _commit = fetch_catalog(str(plain), None, tmp_path / "fetched")

    assert (outside / "notes.txt").read_bytes() == b"theirs\r\n"
    assert (fetched / "base" / PACK / "tree").is_symlink()


def test_a_clone_checks_out_lf_whatever_the_global_autocrlf_says(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Windows' usual `core.autocrlf=true` flipped every text file of a fetched pack to CRLF, and verify failed."""
    catalog, head = tmp_path / "catalog", _catalog(tmp_path / "catalog")
    gitconfig = tmp_path / "gitconfig"
    gitconfig.write_text("[core]\n\tautocrlf = true\n", encoding="utf-8")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(gitconfig))

    pinned, _ = fetch_catalog(f"file://{catalog}", head, tmp_path / "pinned")
    branch, _ = fetch_catalog(f"file://{catalog}", "main", tmp_path / "branch")
    local, _ = fetch_catalog(str(catalog), None, tmp_path / "local")

    for fetched in (pinned, branch, local):
        assert (fetched / "base" / PACK / "a.txt").read_bytes() == b"a\n"
        assert compute_pack_hash(fetched / "base" / PACK) == PINNED_DIGEST
