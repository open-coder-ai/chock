"""A selection path that is not a regular file at the base or in the worktree is a named error, never absent."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from chock.validation.checks_baseline import main
from chock.validation.selection_baseline import AGENTIC, JAVA

DENY_JAVA = '{"version": 2, "packs": {"java": {"verdict": "deny"}}}'
ALLOW_JAVA = '{"version": 2, "packs": {"java": {"verdict": "allow"}}}'
DENY_AGENTIC = '{"version": 1, "packs": {"exec": {"verdict": "deny"}}}'
OBJECT_KINDS = ("symlink", "directory", "submodule")


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def _init(repo: Path) -> None:
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@e")
    _git(repo, "config", "user.name", "t")


def _index_entry(repo: Path, mode: str, sha: str, path: str) -> None:
    _git(repo, "update-index", "--add", "--cacheinfo", f"{mode},{sha},{path}")


def _commit_object(repo: Path, kind: str, path: str) -> None:
    """Commit `path` as a symlink, a directory (with a file inside) or a submodule gitlink."""
    if kind == "symlink":
        blob = subprocess.run(
            ["git", "-C", str(repo), "hash-object", "-w", "--stdin"],
            input="elsewhere.json",
            text=True,
            check=True,
            capture_output=True,
        ).stdout.strip()
        _index_entry(repo, "120000", blob, path)
    elif kind == "directory":
        (repo / path).mkdir(parents=True)
        (repo / path / "inner.txt").write_text("x\n", encoding="utf-8")
        _git(repo, "add", path)
    else:
        _index_entry(repo, "160000", "1" * 40, path)
    _git(repo, "commit", "-qm", "base")


def _clean_repo(tmp_path: Path, files: dict[str, str]) -> Path:
    repo = tmp_path / "repo"
    _init(repo)
    (repo / ".chock").mkdir()
    for name, body in {"README.md": "x\n", **files}.items():
        (repo / name).write_text(body, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")
    return repo


def _run(repo: Path, capsys: pytest.CaptureFixture) -> tuple[int, str]:
    code = main(["--repo", str(repo), "--base", "main"])
    return code, capsys.readouterr().out


@pytest.mark.parametrize("kind", [JAVA, AGENTIC])
@pytest.mark.parametrize("odd", OBJECT_KINDS)
def test_a_base_selection_that_is_not_a_regular_file_is_named(tmp_path, kind, odd, capsys) -> None:
    repo = tmp_path / "repo"
    _init(repo)
    _commit_object(repo, odd, kind.filename)
    code, out = _run(repo, capsys)
    assert code == 1
    expected = {"symlink": "a symlink", "directory": "a directory", "submodule": "a submodule"}[odd]
    assert f"{kind.filename} is {expected} at main" in out
    assert "cannot be trusted as a baseline" in out


@pytest.mark.parametrize("odd", ["symlink", "submodule"])
def test_a_base_chock_that_is_not_a_directory_is_named(tmp_path: Path, odd: str, capsys) -> None:
    repo = tmp_path / "repo"
    _init(repo)
    _commit_object(repo, odd, ".chock")
    code, out = _run(repo, capsys)
    assert code == 1
    assert f".chock is a {odd} at main, not a directory" in out


def test_a_base_chock_that_is_a_file_is_named(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    repo = tmp_path / "repo"
    _init(repo)
    (repo / ".chock").write_text("x\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")
    code, out = _run(repo, capsys)
    assert code == 1
    assert ".chock is a file at main, not a directory" in out


def test_a_symlinked_base_selection_never_reads_as_absent(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    """Absent at base would let a head file that allows everything pass for java."""
    repo = tmp_path / "repo"
    _init(repo)
    _commit_object(repo, "symlink", JAVA.filename)
    (repo / ".chock").mkdir()
    (repo / JAVA.filename).write_text(ALLOW_JAVA, encoding="utf-8")
    code, out = _run(repo, capsys)
    assert code == 1
    assert "a symlink at main" in out


@pytest.mark.parametrize("kind_file", [(JAVA, DENY_JAVA), (AGENTIC, DENY_AGENTIC)])
def test_regular_files_at_base_and_head_still_compare(tmp_path, kind_file, capsys) -> None:
    kind, body = kind_file
    repo = _clean_repo(tmp_path, {kind.filename: body})
    assert _run(repo, capsys)[0] == 0


def test_a_loosened_regular_file_still_fails_on_the_comparison(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    repo = _clean_repo(tmp_path, {JAVA.filename: DENY_JAVA})
    (repo / JAVA.filename).write_text(ALLOW_JAVA, encoding="utf-8")
    code, out = _run(repo, capsys)
    assert code == 1
    assert "deny -> allow" in out


def test_an_executable_regular_file_at_base_compares(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    repo = _clean_repo(tmp_path, {JAVA.filename: DENY_JAVA})
    (repo / JAVA.filename).chmod(0o755)
    _git(repo, "update-index", "--chmod=+x", JAVA.filename)
    _git(repo, "commit", "-qm", "exec")
    assert _run(repo, capsys)[0] == 0


def test_a_worktree_chock_that_is_a_file_is_named(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    repo = _clean_repo(tmp_path, {})
    os.rmdir(repo / ".chock")
    (repo / ".chock").write_text("x\n", encoding="utf-8")
    code, out = _run(repo, capsys)
    assert code == 1
    assert ".chock is a file, not a directory" in out
    assert "falls back" in out
    assert "Not a directory" not in out
