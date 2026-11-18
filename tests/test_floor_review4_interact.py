"""Review 4, item 4: interactions. Each asserts the exit the spec owes (or, where marked, the exit observed by design)."""

from __future__ import annotations

import contextlib
import os
import shutil
import time

from floor_support import base_repo, commit, git, run_floor, write
from floor_support4 import raw_commit


def test_head_deletes_whole_chock_tree(tmp_path, capsys):
    repo = base_repo(tmp_path)
    shutil.rmtree(repo / ".chock")
    commit(repo, "pr")
    code, out = run_floor(repo, capsys)
    assert code == 1, out


def test_mode_only_changes(tmp_path, capsys):
    for i, (path, owed) in enumerate(
        (("src/app.py", 0), (".claude/settings.json", 1), (".agents/policies/probe/implementations/probe.py", 1))
    ):
        repo = base_repo(tmp_path / str(i))
        (repo / path).chmod(0o755)
        commit(repo, "pr")
        code, out = run_floor(repo, capsys)
        assert code == owed, (path, out)


def test_merge_resolution_introduces_a_token_neither_parent_has(tmp_path, capsys):
    repo = base_repo(tmp_path)
    write(repo, "src/app.py", "VALUE = 'left'\n")
    commit(repo, "left")
    git(repo, "checkout", "-q", "-b", "right", "main")
    write(repo, "src/app.py", "VALUE = 'right'\n")
    commit(repo, "right")
    git(repo, "checkout", "-q", "pr")
    with contextlib.suppress(Exception):  # a conflict is expected
        git(repo, "-c", "user.name=t", "-c", "user.email=t@e", "merge", "-q", "--no-edit", "right")
    write(repo, "src/app.py", "VALUE = 'FLOOR-TOKEN-99'\n")
    git(repo, "add", "-A")
    raw_commit(repo, "merge with an evil resolution")
    assert len(git(repo, "rev-list", "--parents", "-n1", "HEAD").split()) == 3
    code, out = run_floor(repo, capsys)
    assert code == 1, out


def test_clean_merge_resolution_with_token_in_resolution_only_history(tmp_path, capsys):
    """Token added by the merge commit and removed in the next commit: only the history pass can see it."""
    repo = base_repo(tmp_path)
    write(repo, "src/a.py", "A = 1\n")
    commit(repo, "left")
    git(repo, "checkout", "-q", "-b", "right", "main")
    write(repo, "src/b.py", "B = 1\n")
    commit(repo, "right")
    git(repo, "checkout", "-q", "pr")
    git(repo, "-c", "user.name=t", "-c", "user.email=t@e", "merge", "-q", "--no-commit", "right")
    write(repo, "src/c.py", "C = 'FLOOR-TOKEN-5'\n")
    git(repo, "add", "-A")
    raw_commit(repo, "merge")
    os.remove(repo / "src/c.py")
    commit(repo, "remove it")
    code, out = run_floor(repo, capsys)
    assert code == 1, out


def test_control_plane_change_and_revert_secret_in_history(tmp_path, capsys):
    """Commit 1 puts a token in .claude/notes.json, commit 2 removes it: the tree diff is empty. S2: still named."""
    repo = base_repo(tmp_path)
    write(repo, ".claude/notes.json", '{"k": "FLOOR-TOKEN-42"}\n')
    commit(repo, "add")
    os.remove(repo / ".claude/notes.json")
    commit(repo, "remove")
    code, out = run_floor(repo, capsys)
    assert code == 1, out
    assert "\n  .claude/notes.json  (in a commit of the range only" in out, out


def test_same_outside_the_control_plane_for_contrast(tmp_path, capsys):
    repo = base_repo(tmp_path)
    write(repo, "src/notes.json", '{"k": "FLOOR-TOKEN-42"}\n')
    commit(repo, "add")
    os.remove(repo / "src/notes.json")
    commit(repo, "remove")
    code, out = run_floor(repo, capsys)
    assert code == 1, out


def test_first_adoption_with_violation(tmp_path, capsys):
    """V6: base without .chock exits 0 even when the head adds .chock and a token."""
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    write(repo, "src/app.py", "VALUE = 1\n")
    commit(repo, "base")
    git(repo, "checkout", "-q", "-b", "pr")
    write(repo, ".chock/config.yaml", "rollout: enforce\n")
    write(repo, "src/app.py", "VALUE = 'FLOOR-TOKEN-1'\n")
    write(repo, ".claude/settings.json", "{}\n")
    commit(repo, "pr")
    code, out = run_floor(repo, capsys)
    assert code == 0 and "nothing was judged" in out, out


def test_many_files(tmp_path, capsys):
    repo = base_repo(tmp_path)
    for i in range(3000):
        write(repo, f"gen/f{i:05d}.py", f"V{i} = {i}\n")
    commit(repo, "pr")
    start = time.monotonic()
    code, out = run_floor(repo, capsys)
    print(f"3000 files: exit {code} in {time.monotonic() - start:.1f}s")
    assert code == 0, out[-800:]
    write(repo, "gen/f01234.py", "V = 'FLOOR-TOKEN-3'\n")
    commit(repo, "pr2")
    code, out = run_floor(repo, capsys)
    assert code == 1, out[-800:]
