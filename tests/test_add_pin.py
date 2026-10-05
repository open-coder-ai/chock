"""A catalog pin that looks like a SHA is a commit object, never a branch or tag of that name."""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

from chock.scaffold import pin
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
    with pytest.raises(PinError, match="commit not available from the remote by id"):
        add(repo, ID, _src(root), missing, force=False)
    assert not _installed(repo)
    assert good != evil


def test_a_tag_named_like_the_sha_cannot_stand_in_for_it(remote, repo: Path) -> None:
    root, _, evil = remote
    missing = "b" * 40
    _git(root, "tag", missing, evil)
    with pytest.raises(PinError, match="commit not available from the remote by id"):
        add(repo, ID, _src(root), missing, force=False)
    assert not _installed(repo)


def test_a_tag_named_like_the_good_sha_cannot_redirect_it(remote, repo: Path) -> None:
    root, good, evil = remote
    _git(root, "tag", good, evil)
    added = add(repo, ID, _src(root), good, force=False)
    assert added.commit == good
    assert "good" in (added.path / "SKILL.md").read_text(encoding="utf-8")


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


def _global_git_config(tmp_path: Path, monkeypatch, body: str) -> Path:
    """A user-level git config in a temp HOME, visible to the code under test only."""
    home = tmp_path / "home"
    home.mkdir()
    (home / ".gitconfig").write_text(body, encoding="utf-8")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    return home


def _orphan(root: Path, good: str) -> str:
    _git(root, "config", "uploadpack.allowAnySHA1InWant", "false")
    return _git(root, "commit-tree", "-m", "orphan", f"{good}^{{tree}}")


def test_protocol_v0_remote_will_not_serve_an_unadvertised_commit_by_id(
    remote, repo: Path, tmp_path: Path, monkeypatch
) -> None:
    root, good, _ = remote
    orphan = _orphan(root, good)
    _global_git_config(tmp_path, monkeypatch, "[protocol]\n\tversion = 0\n")
    with pytest.raises(PinError, match="commit not available from the remote by id"):
        add(repo, ID, _src(root), orphan, force=False)
    assert not _installed(repo)


def test_protocol_v2_serves_only_the_pinned_commit(remote, repo: Path, tmp_path: Path, monkeypatch) -> None:
    root, good, _ = remote
    orphan = _orphan(root, good)
    _global_git_config(tmp_path, monkeypatch, "[protocol]\n\tversion = 2\n")
    try:
        added = add(repo, ID, _src(root), orphan, force=False)
    except PinError:
        assert not _installed(repo)
        return
    assert added.commit == orphan


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


def test_a_commit_suffix_on_a_sha_is_not_a_ref(remote, repo: Path) -> None:
    root, good, _ = remote
    with pytest.raises(PinError, match="not a valid git ref name"):
        add(repo, ID, _src(root), f"{good}^{{commit}}", force=False)


def test_the_cli_exits_2_and_installs_nothing_for_a_short_sha(remote, repo: Path, capsys) -> None:
    root, good, _ = remote
    code = main([ID, "--repo", str(repo), "--from", _src(root), "--ref", good[:12], "--skip-compile"])
    assert code == 2
    assert "pin a full 40-character commit SHA" in capsys.readouterr().err
    assert not _installed(repo)


def test_the_cli_exits_2_and_installs_nothing_for_an_option_like_ref(remote, repo: Path, capsys) -> None:
    root, _, _ = remote
    code = main([ID, "--repo", str(repo), "--from", _src(root), "--ref=--upload-pack=touch pwned", "--skip-compile"])
    assert code == 2
    assert "not a valid git ref name" in capsys.readouterr().err
    assert not _installed(repo)
    assert not (repo / "pwned").exists()


@pytest.mark.parametrize("by", ["sha", "branch"])
def test_an_inherited_git_dir_does_not_redirect_the_fetch(remote, repo: Path, tmp_path: Path, monkeypatch, by) -> None:
    root, good, _ = remote
    victim = tmp_path / "victim"
    victim.mkdir()
    _git(victim, "init", "--quiet", "-b", "main")
    _git(victim, "config", "user.email", "v@example.invalid")
    _git(victim, "config", "user.name", "Victim")
    (victim / "f").write_text("v", encoding="utf-8")
    _git(victim, "add", "f")
    _git(victim, "commit", "--quiet", "-m", "victim")
    index = victim / ".git" / "index"
    before = (_git(victim, "rev-parse", "HEAD"), _git(victim, "symbolic-ref", "HEAD"), index.read_bytes())
    for var in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"):
        monkeypatch.setenv(var, {"GIT_DIR": str(victim / ".git"), "GIT_WORK_TREE": str(victim)}.get(var, str(index)))
    added = add(repo, ID, _src(root), good if by == "sha" else "main", force=False)
    for var in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"):
        monkeypatch.delenv(var)
    after = (_git(victim, "rev-parse", "HEAD"), _git(victim, "symbolic-ref", "HEAD"), index.read_bytes())
    assert after == before
    assert added.commit == good
    assert "good" in (added.path / "SKILL.md").read_text(encoding="utf-8")


@pytest.mark.skipif(os.name == "nt", reason="posix shell hooks")
@pytest.mark.parametrize("ref", ["sha", "branch"])
def test_user_level_hooks_templates_and_fsmonitor_do_not_run(
    remote, repo: Path, tmp_path: Path, monkeypatch, ref
) -> None:
    root, good, _ = remote
    marker = tmp_path / "ran"
    hook = "#!/bin/sh\ntouch '" + str(marker) + "'\n"
    template = tmp_path / "tpl"
    (template / "hooks").mkdir(parents=True)
    hooks = tmp_path / "hooks"
    hooks.mkdir()
    fsmonitor = tmp_path / "fsmonitor"
    for path in (template / "hooks" / "post-checkout", hooks / "post-checkout", fsmonitor):
        path.write_text(hook, encoding="utf-8")
        path.chmod(0o755)
    config = f"[init]\n\ttemplateDir = {template}\n[core]\n\tfsmonitor = {fsmonitor}\n\thooksPath = {hooks}\n"
    _global_git_config(tmp_path, monkeypatch, config)
    added = add(repo, ID, _src(root), good if ref == "sha" else "main", force=False)
    assert added.commit == good
    assert not marker.exists()


@pytest.mark.parametrize("source", ["ext::sh -c 'touch pwned'", "fd::3", "ext::false"])
@pytest.mark.parametrize("ref", [None, "c" * 40])
def test_transport_helper_sources_are_refused_quickly(repo: Path, tmp_path: Path, monkeypatch, source, ref) -> None:
    monkeypatch.chdir(tmp_path)
    start = time.monotonic()
    with pytest.raises((PinError, RuntimeError)):
        add(repo, ID, source, ref, force=False)
    assert time.monotonic() - start < 30
    assert not (tmp_path / "pwned").exists()
    assert not _installed(repo)


def test_a_git_timeout_is_a_clean_refusal(remote, repo: Path, monkeypatch) -> None:
    root, good, _ = remote

    def hang(args, **kwargs):
        raise subprocess.TimeoutExpired(args, kwargs["timeout"])

    monkeypatch.setattr(pin.subprocess, "run", hang)
    with pytest.raises(PinError, match="timed out"):
        add(repo, ID, _src(root), good, force=False)
    with pytest.raises(RuntimeError, match="timed out"):
        add(repo, ID, _src(root), "main", force=False)
    assert not _installed(repo)


def test_git_env_drops_redirecting_variables_and_keeps_ssh_and_proxy(monkeypatch) -> None:
    for name in ("GIT_DIR", "GIT_CONFIG_COUNT", "GIT_CONFIG_KEY_0", "GIT_CONFIG_PARAMETERS", "GIT_EXEC_PATH"):
        monkeypatch.setenv(name, "x")
    for name in ("GIT_SSH_COMMAND", "HTTPS_PROXY", "GIT_SSL_CAINFO"):
        monkeypatch.setenv(name, "keep")
    monkeypatch.setenv("GIT_ALLOW_PROTOCOL", "ext")
    env = pin.git_env()
    assert not {"GIT_DIR", "GIT_CONFIG_COUNT", "GIT_CONFIG_KEY_0", "GIT_CONFIG_PARAMETERS", "GIT_EXEC_PATH"} & set(env)
    assert env["GIT_SSH_COMMAND"] == env["HTTPS_PROXY"] == env["GIT_SSL_CAINFO"] == "keep"
    assert env["GIT_ALLOW_PROTOCOL"] == pin.ALLOWED_PROTOCOLS


def _only_under(root: Path, ref: str, body: str) -> str:
    """A commit reachable from `ref` alone: made on a throwaway branch, then the branch is deleted."""
    _git(root, "checkout", "--quiet", "-b", "scratch", "main")
    sha = _commit(root, body)
    _git(root, "update-ref", ref, sha)
    _git(root, "checkout", "--quiet", "main")
    _git(root, "branch", "-D", "scratch")
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
        _git(other, *args)
    stranger = _commit(other, "stranger")
    with pytest.raises(PinError, match="commit not available from the remote by id"):
        add(repo, ID, _src(root), stranger, force=False)
    assert not _installed(repo)


def test_a_local_directory_source_is_not_checked_for_published_refs(remote, repo: Path) -> None:
    root, _, _ = remote
    pulled = _only_under(root, "refs/pull/1/head", "pulled")
    added = add(repo, ID, str(root), pulled, force=False)
    assert added.commit == pulled
