"""Second adversarial review of `chock check --floor`, part 2: refs, encodings, waivers, history, correct PRs.

Each asserts the exit W2-A1v2 owes. Control-plane proofs of the same review are in test_floor_attacks3.py.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

import pytest
from floor_support import (
    FLOOR_TOKEN,
    LOCK,
    TEST_FILE,
    TEST_PRAGMA,
    base_repo,
    commit,
    control_plane_change,
    gate,
    git,
    run_floor,
    write,
)

SECRET = "FLOOR-TOKEN-424242"


def _merge(repo: Path, branch: str = "pr") -> None:
    git(repo, "-c", "user.name=t", "-c", "user.email=t@e", "merge", "-q", "--no-ff", "--no-edit", branch)


# ---------- shallow clone and unrelated history ----------


def test_shallow_clone_is_undecided(tmp_path, capsys):
    repo = base_repo(tmp_path)
    write(repo, "src/app.py", "VALUE = 2\n")
    commit(repo, "pr1")
    write(repo, "src/app.py", "VALUE = 3\n")
    commit(repo, "pr2")
    clone = tmp_path / "clone"
    subprocess.run(
        ["git", "clone", "-q", "--depth", "1", "--no-single-branch", f"file://{repo}", str(clone)], check=True
    )
    code, out = run_floor(clone, capsys, "--base", "origin/main", "--head", "origin/pr")
    assert code == 2, out


def test_unrelated_history_is_undecided(tmp_path, capsys):
    repo = base_repo(tmp_path)
    git(repo, "checkout", "-q", "--orphan", "alien")
    git(repo, "rm", "-rq", "--cached", ".")
    write(repo, "x.txt", f"{SECRET}\n")
    git(repo, "add", "x.txt")
    git(repo, "-c", "user.name=t", "-c", "user.email=t@e", "commit", "-q", "-m", "alien")
    code, out = run_floor(repo, capsys, "--head", "alien")
    assert code == 2, out


# ---------- M-f, X6: encodings and line counting in the history pass ----------


def test_utf16_secret(tmp_path, capsys):
    repo = base_repo(tmp_path)
    (repo / "src/notes.txt").write_bytes(f"key = {SECRET}\n".encode("utf-16"))
    commit(repo, "pr")
    code, out = run_floor(repo, capsys)
    assert code == 1, out
    assert "floor-token [history] (block)" in out


def test_utf16_secret_shifted_by_one_byte(tmp_path, capsys):
    repo = base_repo(tmp_path)
    (repo / "src/notes.bin").write_bytes(b"\x01" + f"key = {SECRET}\n".encode("utf-16-le"))
    commit(repo, "pr")
    code, out = run_floor(repo, capsys)
    assert code == 1, out


def test_secret_as_symlink_target_added_then_removed(tmp_path, capsys):
    repo = base_repo(tmp_path)
    os.symlink(SECRET, repo / "link")
    commit(repo, "add link")
    (repo / "link").unlink()
    commit(repo, "remove link")
    code, out = run_floor(repo, capsys)
    assert code == 1, out


@pytest.mark.parametrize("prefix", [b"\x85\x85", b"\xff\xff", b"\x1c\x1d\x1e"])
def test_history_line_number_mismatch_drops_no_secret(tmp_path, capsys, prefix):
    """U+0085 and the separators splitlines() knows are not line breaks to the floor: one reader, one count."""
    repo = base_repo(tmp_path)
    (repo / "src/app.py").write_bytes(prefix + b"FLOOR-TOKEN-777\nVALUE = 1\nVALUE = 1\n")
    commit(repo, "pr: add (hidden)")
    write(repo, "src/app.py", "VALUE = 1\n")
    commit(repo, "pr: restore")
    code, out = run_floor(repo, capsys)
    assert code == 1, out
    assert "src/app.py:1 (content-pattern)" in out


# ---------- M-a, M-b: waivers on removed lines, renames hiding deletions ----------


def _base_then_pr(repo: Path, base_text: str, head_text: str) -> None:
    git(repo, "checkout", "-q", "main")
    write(repo, "tests/test_core.py", base_text)
    commit(repo, "base")
    git(repo, "checkout", "-q", "-B", "pr")
    write(repo, "tests/test_core.py", head_text)
    commit(repo, "pr")


def test_removed_assertion_carrying_base_pragma_is_not_waived(tmp_path, capsys):
    repo = base_repo(tmp_path)
    pragma = TEST_FILE.replace("assert 2 * 2 == 4", f"assert 2 * 2 == 4  # {TEST_PRAGMA}")
    _base_then_pr(repo, pragma, "def test_a():\n    assert 1 + 1 == 2\n")
    code, out = run_floor(repo, capsys)
    assert code == 1, out


def test_removed_pragma_assertions_two_lines(tmp_path, capsys):
    repo = base_repo(tmp_path)
    body = TEST_FILE.replace("== 2\n", f"== 2  # {TEST_PRAGMA}\n").replace("== 4\n", f"== 4  # {TEST_PRAGMA}\n")
    _base_then_pr(repo, body, "def test_a():\n    pass\n")
    code, out = run_floor(repo, capsys)
    assert code == 1, out


@pytest.mark.parametrize("how", ["rename", "delete", "weaken"])
def test_test_file_moved_deleted_or_weakened_is_refused(tmp_path, capsys, how):
    repo = base_repo(tmp_path)
    if how == "rename":
        git(repo, "mv", "tests/test_core.py", "attic_core.py")
    elif how == "delete":
        git(repo, "rm", "-q", "tests/test_core.py")
    else:
        write(repo, "tests/test_core.py", "def test_a():\n    assert 1 + 1 == 2\n")
    commit(repo, "pr")
    code, out = run_floor(repo, capsys)
    assert code == 1, out


# ---------- first adoption ----------


def test_first_adoption_output(tmp_path, capsys):
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    write(repo, "src/app.py", "V = 1\n")
    commit(repo, "base")
    git(repo, "checkout", "-q", "-b", "pr")
    write(repo, "src/leak.py", "K = 'FLOOR-TOKEN-1'\n")
    commit(repo, "pr")
    code, out = run_floor(repo, capsys)
    assert code == 0, out
    assert "base has no chock gates; nothing was judged" in out


# ---------- correct pull requests and wall time ----------


@pytest.mark.parametrize("megabytes", [8, 40])
def test_large_correct_blob(tmp_path, capsys, megabytes):
    repo = base_repo(tmp_path)
    line = "a,b,c,d,e,f,g,h,i,j,k,l,m,n,o,p,q,r,s,t,u,v,w,x,y,z,0123456789\n"
    (repo / "data.csv").write_text(line * (megabytes * 1024 * 1024 // len(line)))
    commit(repo, "pr: data")
    started = time.monotonic()
    code, out = run_floor(repo, capsys)
    print(f"{megabytes} MB: exit {code} in {time.monotonic() - started:.1f}s")
    assert code == 0, out


def test_ok_merge_base_into_branch_and_revert(tmp_path, capsys):
    repo = base_repo(tmp_path)
    write(repo, "src/feature.py", "F = 1\n")
    commit(repo, "pr: feature")
    git(repo, "checkout", "-q", "main")
    write(repo, "src/other.py", "O = 1\n")
    commit(repo, "main moves on")
    git(repo, "checkout", "-q", "pr")
    _merge(repo, "main")
    write(repo, "src/feature.py", "F = 2\n")
    commit(repo, "pr: change")
    git(repo, "-c", "user.name=t", "-c", "user.email=t@e", "revert", "--no-edit", "HEAD")
    code, out = run_floor(repo, capsys)
    assert code == 0, out


def test_policy_added_with_lock_entry_is_a_control_plane_change(tmp_path, capsys):
    """By design under `refuse` (a privileged merge); under `listed` its own gate never judges its own source."""

    def change(repo):
        lock = json.loads(json.dumps(LOCK))
        lock["packs"].append({"id": "no-todo"})
        write(repo, "chock.lock", lock)
        gate(repo, "no-todo", dict(FLOOR_TOKEN, message="no TODO", params={"content_pattern": "TODO-NEVER"}))
        write(repo, ".agents/policies/no-todo/policy.md", "# no-todo\n")
        commit(repo, "pr: add policy")

    control_plane_change(tmp_path, capsys, change, "chock.lock", ".agents/policies/no-todo/policy.md")


def test_docs_quoting_a_policy_example_in_its_own_folder(tmp_path, capsys):
    rel = ".agents/policies/floor-token/README.md"

    def change(repo):
        write(repo, rel, "Example that is refused: FLOOR-TOKEN-1\n")
        commit(repo, "pr: docs")

    control_plane_change(tmp_path, capsys, change, rel)


def test_ok_rename_file_with_base_waiver(tmp_path, capsys):
    """A rename is a delete and an add (V1); the fixture's probe gate refuses every delete, so it goes first."""
    repo = base_repo(tmp_path)
    git(repo, "checkout", "-q", "main")
    git(repo, "rm", "-q", "-r", ".chock/compiled/probe")
    write(repo, "src/legacy.py", "X = 1\n")
    commit(repo, "base")
    git(repo, "checkout", "-q", "-B", "pr")
    git(repo, "mv", "src/legacy.py", "src/legacy2.py")
    commit(repo, "pr: rename")
    code, out = run_floor(repo, capsys)
    assert code == 0, out
