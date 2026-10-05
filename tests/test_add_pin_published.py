"""A pinned commit must be on a branch or tag the source publishes; a fork's or a pull request's is refused."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from add_pin_support import ID, commit, git, make_remote

from chock.scaffold.add import PinError, add

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git required")


@pytest.fixture
def remote(tmp_path: Path) -> tuple[Path, str, str]:
    return make_remote(tmp_path)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    r = tmp_path / "repo"
    r.mkdir()
    git(r, "init", "--quiet", ".")
    return r


def _src(root: Path) -> str:
    return f"file://{root}"


def _installed(repo: Path) -> bool:
    return (repo / ".agents" / "skills" / ID).exists()


def _only_under(root: Path, ref: str, body: str) -> str:
    """A commit reachable from `ref` alone: made on a throwaway branch, then the branch is deleted."""
    git(root, "checkout", "--quiet", "-b", "scratch", "main")
    sha = commit(root, body)
    git(root, "update-ref", ref, sha)
    git(root, "checkout", "--quiet", "main")
    git(root, "branch", "-D", "scratch")
    return sha


def test_a_commit_on_a_branch_of_the_source_is_accepted(remote, repo: Path) -> None:
    root, good, _ = remote
    added = add(repo, ID, _src(root), good, force=False)
    assert added.commit == good
    assert "good" in (added.path / "SKILL.md").read_text(encoding="utf-8")


def test_a_commit_reachable_only_from_a_tag_is_accepted(remote, repo: Path) -> None:
    root, _, _ = remote
    tagged = _only_under(root, "refs/tags/v1", "tagged")
    added = add(repo, ID, _src(root), tagged, force=False)
    assert added.commit == tagged
    assert "tagged" in (added.path / "SKILL.md").read_text(encoding="utf-8")


def test_a_commit_only_under_a_pull_request_ref_is_refused(remote, repo: Path) -> None:
    root, _, _ = remote
    pulled = _only_under(root, "refs/pull/1/head", "pulled")
    with pytest.raises(PinError) as caught:
        add(repo, ID, _src(root), pulled, force=False)
    assert (
        f"commit {pulled} is not on any branch or tag of {_src(root)}; a fork's or a pull request's commit is refused"
        in str(caught.value)
    )
    assert not _installed(repo)


def test_a_commit_from_an_unrelated_repository_is_refused_as_unavailable(remote, repo: Path, tmp_path: Path) -> None:
    root, _, _ = remote
    other = tmp_path / "other"
    other.mkdir()
    for args in (
        ("init", "--quiet", "-b", "main"),
        ("config", "user.email", "o@example.invalid"),
        ("config", "user.name", "O"),
    ):
        git(other, *args)
    stranger = commit(other, "stranger")
    with pytest.raises(PinError, match="commit not available from the remote by id"):
        add(repo, ID, _src(root), stranger, force=False)
    assert not _installed(repo)


def test_a_local_directory_source_is_not_checked_for_published_refs(remote, repo: Path) -> None:
    root, _, _ = remote
    pulled = _only_under(root, "refs/pull/1/head", "pulled")
    added = add(repo, ID, str(root), pulled, force=False)
    assert added.commit == pulled
