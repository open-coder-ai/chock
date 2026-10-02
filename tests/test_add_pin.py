"""A catalog pin that looks like a SHA is a commit object, never a branch or tag of that name."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from chock.scaffold.add import PinError, add, main

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git required")

ID = "demo-skill"


def _git(cwd: Path, *args: str) -> str:
    done = subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)
    return done.stdout.strip()


def _commit(root: Path, body: str) -> str:
    skill = root / "skills" / ID
    skill.mkdir(parents=True, exist_ok=True)
    (skill / "SKILL.md").write_text(f"---\nname: {ID}\ndescription: demo\n---\n\n{body}\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "--quiet", "-m", body)
    return _git(root, "rev-parse", "HEAD")


@pytest.fixture
def remote(tmp_path: Path) -> tuple[Path, str, str]:
    """A catalog repo: (path, pinned good commit, a different commit)."""
    root = tmp_path / "catalog"
    root.mkdir()
    for args in (
        ("init", "--quiet", "-b", "main"),
        ("config", "user.email", "c@example.invalid"),
        ("config", "user.name", "Catalog"),
        ("config", "uploadpack.allowAnySHA1InWant", "true"),
    ):
        _git(root, *args)
    good = _commit(root, "good")
    _git(root, "checkout", "--quiet", "-b", "other")
    evil = _commit(root, "evil")
    _git(root, "checkout", "--quiet", "main")
    return root, good, evil


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    r = tmp_path / "repo"
    r.mkdir()
    _git(r, "init", "--quiet", ".")
    return r


def _src(root: Path) -> str:
    return f"file://{root}"


def _installed(repo: Path) -> bool:
    return (repo / ".agents" / "skills" / ID).exists()


def test_a_branch_named_like_the_sha_cannot_stand_in_for_it(remote, repo: Path) -> None:
    root, good, evil = remote
    missing = "a" * 40
    _git(root, "branch", missing, evil)
    with pytest.raises(PinError):
        add(repo, ID, _src(root), missing, force=False)
    assert not _installed(repo)
    assert good != evil


def test_a_tag_named_like_the_sha_cannot_stand_in_for_it(remote, repo: Path) -> None:
    root, _, evil = remote
    missing = "b" * 40
    _git(root, "tag", missing, evil)
    with pytest.raises(PinError):
        add(repo, ID, _src(root), missing, force=False)
    assert not _installed(repo)


def test_a_branch_named_like_the_sha_does_not_shadow_the_real_commit(remote, repo: Path) -> None:
    root, good, evil = remote
    _git(root, "branch", good, evil)
    added = add(repo, ID, _src(root), good, force=False)
    assert added.commit == good
    assert "good" in (added.path / "SKILL.md").read_text(encoding="utf-8")


def test_a_short_sha_is_refused(remote, repo: Path) -> None:
    root, good, _ = remote
    with pytest.raises(PinError, match="pin a full 40-character commit SHA"):
        add(repo, ID, _src(root), good[:12], force=False)
    assert not _installed(repo)


def test_a_short_hex_branch_name_is_not_resolved_as_a_branch(remote, repo: Path) -> None:
    root, _, evil = remote
    _git(root, "branch", "deadbeef", evil)
    with pytest.raises(PinError, match="full 40-character"):
        add(repo, ID, _src(root), "deadbeef", force=False)


def test_a_full_sha_absent_from_the_remote_is_refused_with_exit_2(remote, repo: Path, capsys) -> None:
    root, _, _ = remote
    code = main([ID, "--repo", str(repo), "--from", _src(root), "--ref", "c" * 40, "--skip-compile"])
    assert code == 2
    assert "nothing installed" in capsys.readouterr().err
    assert not _installed(repo)


def test_a_remote_that_will_not_serve_a_commit_by_id_is_refused(remote, repo: Path, monkeypatch) -> None:
    root, good, _ = remote
    _git(root, "config", "uploadpack.allowAnySHA1InWant", "false")
    orphan = _git(root, "commit-tree", "-m", "orphan", f"{good}^{{tree}}")
    for key, value in (
        ("GIT_CONFIG_COUNT", "1"),
        ("GIT_CONFIG_KEY_0", "protocol.version"),
        ("GIT_CONFIG_VALUE_0", "0"),
    ):
        monkeypatch.setenv(key, value)
    with pytest.raises(PinError):
        add(repo, ID, _src(root), orphan, force=False)
    assert not _installed(repo)


def test_a_full_sha_installs_that_commit(remote, repo: Path) -> None:
    root, good, _ = remote
    added = add(repo, ID, _src(root), good, force=False)
    assert added.commit == good
    assert "good" in (added.path / "SKILL.md").read_text(encoding="utf-8")


def test_an_uppercase_sha_is_normalised(remote, repo: Path) -> None:
    root, good, _ = remote
    assert add(repo, ID, _src(root), good.upper(), force=False).commit == good


def test_a_branch_ref_works_warns_and_records_the_commit(remote, repo: Path, capsys) -> None:
    root, good, _ = remote
    _git(root, "branch", "stable", good)
    added = add(repo, ID, _src(root), "stable", force=False)
    assert added.commit == good
    assert "can move" in capsys.readouterr().err


@pytest.mark.parametrize("ref", ["--upload-pack=touch pwned", "-x", "a..b", "a b", "x~1", "a:b", "@{-1}"])
def test_a_ref_that_is_an_option_or_not_a_ref_is_refused(remote, repo: Path, ref: str) -> None:
    root, _, _ = remote
    with pytest.raises(PinError, match="not a valid git ref name"):
        add(repo, ID, _src(root), ref, force=False)
    assert not _installed(repo)
