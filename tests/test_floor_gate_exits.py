"""Release gate G1, GT-2 abnormal paths: F1-F2. None may end as 0 unless the scenario owes it."""

from __future__ import annotations

import os
import subprocess
import sys

import pytest
from floor_support import base_repo, commit, git, run_floor, write

from chock.validation import checks_floor


def _main(capsys, *argv: str) -> tuple[int, str]:
    code = checks_floor.main(list(argv))
    out = capsys.readouterr()
    return code, out.out + out.err


def _pr(tmp_path, path="src/app.py", content="VALUE = 2\n"):
    repo = base_repo(tmp_path)
    write(repo, path, content)
    commit(repo, "pr")
    return repo


def test_f1_base_equal_to_head_is_clean_and_says_nothing_changed(tmp_path, capsys):
    repo = base_repo(tmp_path)
    code, out = _main(capsys, "--repo", str(repo), "--base", "main", "--head", "main")
    assert code == 0, out
    assert "base and head are the same commit; nothing changed" in out, out


def test_f1_a_repository_with_no_commits_is_undecided(tmp_path, capsys):
    repo = tmp_path / "empty"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    code, out = _main(capsys, "--repo", str(repo), "--base", "main", "--head", "HEAD")
    assert code == 2, out
    assert "does not resolve" in out, out


@pytest.mark.parametrize("which", ["--base", "--head"])
def test_f1_a_ref_that_does_not_exist_is_undecided(tmp_path, capsys, which):
    repo = _pr(tmp_path)
    refs = {"--base": "main", "--head": "pr", which: "no-such-ref"}
    code, out = _main(capsys, "--repo", str(repo), "--base", refs["--base"], "--head", refs["--head"])
    assert code == 2, out
    assert "'no-such-ref' does not resolve" in out, out


@pytest.mark.parametrize("obj", ["pr^{tree}", "pr:src/app.py"], ids=["F1-tree", "F1-blob"])
def test_f1_a_head_that_is_a_tree_or_blob_is_undecided(tmp_path, capsys, obj):
    repo = _pr(tmp_path)
    code, out = _main(capsys, "--repo", str(repo), "--base", "main", "--head", git(repo, "rev-parse", obj))
    assert code == 2, out
    assert "does not resolve" in out, out


def test_f1_a_head_that_is_an_annotated_tag_is_judged_as_its_commit(tmp_path, capsys):
    repo = _pr(tmp_path, ".claude/settings.json", "{}\n")
    git(repo, "-c", "user.name=t", "-c", "user.email=t@example.com", "tag", "-a", "-m", "t", "v-pr", "pr")
    by_commit = _main(capsys, "--repo", str(repo), "--base", "main", "--head", "pr")
    by_tag = _main(capsys, "--repo", str(repo), "--base", "main", "--head", "v-pr")
    assert by_tag == by_commit and by_tag[0] == 1, by_tag
    assert f"head {git(repo, 'rev-parse', 'pr')[:12]}" in by_tag[1], by_tag


def test_f2_a_missing_object_is_undecided(tmp_path, capsys):
    """A loose blob of the head deleted from a scratch copy: the floor cannot read it, so it cannot pass it."""
    repo = _pr(tmp_path, "src/new.py", "print('new')\n")
    oid = git(repo, "rev-parse", "pr:src/new.py")
    loose = repo / ".git/objects" / oid[:2] / oid[2:]
    loose.unlink()
    code, out = run_floor(repo, capsys)
    assert code == 2, out


def test_f2_repo_that_is_not_a_repository_is_undecided(tmp_path, capsys):
    plain = tmp_path / "plain"
    plain.mkdir()
    code, out = _main(capsys, "--repo", str(plain), "--base", "main")
    assert code == 2, out
    assert "is not inside a git repository" in out, out


def test_f2_git_absent_from_path_is_undecided(tmp_path):
    repo = _pr(tmp_path)
    env = {"PATH": str(tmp_path / "empty"), "HOME": os.environ["HOME"], "PYTHONPATH": os.pathsep.join(sys.path)}
    script = "import sys; from chock.validation.checks_floor import main; sys.exit(main(sys.argv[1:]))"
    proc = subprocess.run(
        [sys.executable, "-c", script, "--repo", str(repo), "--base", "main"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "git could not run" in proc.stderr, proc.stderr


@pytest.mark.parametrize("target", ["missing/x.sarif", "adir"], ids=["F2-no-parent", "F2-a-directory"])
def test_f2_an_unwritable_sarif_path_is_non_zero_and_says_why(tmp_path, capsys, target):
    repo = _pr(tmp_path)
    (tmp_path / "adir").mkdir()
    code, out = run_floor(repo, capsys, "--sarif", str(tmp_path / target))
    assert code != 0, out
    assert "UNDECIDED floor: cannot write --sarif: " in out, out
