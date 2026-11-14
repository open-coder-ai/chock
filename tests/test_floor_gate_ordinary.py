"""Release gate G1, GT-2 ordinary pull requests: each touches no control-plane path and is owed exit 0."""

from __future__ import annotations

import random

import pytest
from floor_support import TEST_FILE, base_repo, commit, git, run_floor, write

from chock.validation.floor_history import FLOOR_MAX_BLOB_BYTES


def _bytes(repo, rel, data):
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _merge_base_into_branch(repo):
    """main moves on (a source edit), the branch edits a test, then merges main in: the merge is the head."""
    write(repo, "src/feature.py", "FEATURE = 1\n")
    commit(repo, "pr: feature")
    git(repo, "checkout", "-q", "main")
    write(repo, "src/other.py", "OTHER = 1\n")
    commit(repo, "main moves")
    git(repo, "checkout", "-q", "pr")
    git(repo, "-c", "user.name=t", "-c", "user.email=t@example.com", "merge", "-q", "--no-ff", "--no-edit", "main")


def _revert(repo):
    write(repo, "src/app.py", "VALUE = 3\n")
    commit(repo, "pr: change")
    git(repo, "-c", "user.name=t", "-c", "user.email=t@example.com", "revert", "--no-edit", "HEAD")


GENERATED = b"generated_value_0123456789 = 'abcdefghijklmnopqrstuvwxyz'\n" * (4 * 2**20 // 58)

CASES = {
    "source-edit": lambda r: write(r, "src/app.py", "VALUE = 2\n"),
    "new-test-file": lambda r: write(r, "tests/test_new.py", "def test_b():\n    assert 3 > 2\n"),
    "test-gains-assertions": lambda r: write(r, "tests/test_core.py", TEST_FILE + "    assert 3 * 3 == 9\n"),
    "docs-edit": lambda r: write(r, "docs/guide.md", "# Guide\n\nHow to run it.\n"),
    "lockfile-bump": lambda r: write(r, "uv.lock", 'version = 1\n[[package]]\nname = "x"\nversion = "1.1"\n'),
    "new-directory": lambda r: write(r, "pkg/sub/mod.py", "X = 1\n"),
    "binary-asset": lambda r: _bytes(r, "assets/logo.png", b"\x89PNG\r\n\x1a\n" + random.Random(7).randbytes(65536)),  # noqa: S311
    "large-generated-file": lambda r: _bytes(r, "src/generated_table.py", GENERATED),
    "crlf-file": lambda r: _bytes(r, "src/win.py", b"A = 1\r\nB = 2\r\n"),
    "bom-file": lambda r: _bytes(r, "src/bom.py", b"\xef\xbb\xbfA = 1\n"),
}


@pytest.mark.parametrize("name", list(CASES))
def test_ordinary_pull_request_is_clean(tmp_path, capsys, name):
    repo = base_repo(tmp_path)
    CASES[name](repo)
    commit(repo, f"pr: {name}")
    code, out = run_floor(repo, capsys)
    assert code == 0, out
    assert "floor/control-plane-changed" not in out, out


def test_ordinary_large_generated_file_is_under_the_limit():
    assert 2**20 < len(GENERATED) < FLOOR_MAX_BLOB_BYTES  # large, and judged rather than skipped


@pytest.mark.parametrize("build", [_merge_base_into_branch, _revert], ids=["merge-of-base", "revert-commit"])
def test_ordinary_history_shapes_are_clean(tmp_path, capsys, build):
    repo = base_repo(tmp_path)
    build(repo)
    code, out = run_floor(repo, capsys, "--head", "pr")
    assert code == 0, out
    assert "floor/control-plane-changed" not in out, out
