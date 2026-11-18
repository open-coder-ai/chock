"""Review 3 of the floor (W2-A1v2.1 L3, L4, L6, L7): fault paths, ordinary pull requests, no head file runs."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest
from floor_support import PROBE, TEST_FILE, base_repo, commit, git, run_floor, write

from chock.validation import checks_floor, control_plane, floor_git
from chock.validation.checks_floor import main as floor_main

_IDENT = ("-c", "user.name=t", "-c", "user.email=t@example.com")


def _drop_object(repo: Path, oid: str) -> None:
    (repo / ".git/objects" / oid[:2] / oid[2:]).unlink()


def _base_without(tmp_path: Path, *policies: str) -> Path:
    repo = base_repo(tmp_path)
    git(repo, "checkout", "-q", "main")
    for policy in policies:
        shutil.rmtree(repo / ".chock/compiled" / policy)
    commit(repo, f"base: without {', '.join(policies)}")
    git(repo, "checkout", "-q", "-B", "pr")
    return repo


@pytest.mark.parametrize("without", [("floor-token", "test-integrity"), ()])
def test_an_unreadable_head_blob_is_undecided(tmp_path, capsys, without):
    """L3: with a script gate only (no history pass) as with content gates, never '' handed to a gate."""
    repo = _base_without(tmp_path, *without) if without else base_repo(tmp_path)
    write(repo, "src/new.py", "print('x')\n")
    commit(repo, "pr")
    _drop_object(repo, git(repo, "rev-parse", "HEAD:src/new.py"))
    code, out = run_floor(repo, capsys)
    assert code == 2, out
    assert "src/new.py" in out, out


@pytest.mark.parametrize("below", ["src", "tests"])
def test_repo_given_as_a_subdirectory_still_sees_removed_assertions(tmp_path, capsys, below):
    """L4: a workflow with `working-directory:` set, or --repo below the top level."""
    repo = base_repo(tmp_path)
    write(repo, "tests/test_core.py", "def test_a():\n    pass\n")
    commit(repo, "pr")
    code = checks_floor.main(["--repo", str(repo / below), "--base", "main"])
    out = capsys.readouterr()
    assert code == 1, out.out + out.err
    assert "test-integrity" in out.out, out.out


def test_repo_outside_any_repository_is_undecided(tmp_path, capsys):
    (tmp_path / "plain").mkdir()
    code = checks_floor.main(["--repo", str(tmp_path / "plain"), "--base", "main"])
    assert code == 2, capsys.readouterr()


def test_keyboard_interrupt_never_returns_zero(tmp_path, monkeypatch):
    repo = base_repo(tmp_path)
    write(repo, "src/app.py", "VALUE = 2\n")
    commit(repo, "pr")

    def boom(*_a, **_k):
        raise KeyboardInterrupt

    monkeypatch.setattr(floor_git, "changed_paths", boom)
    monkeypatch.setattr(control_plane, "changed_paths", boom)
    with pytest.raises(KeyboardInterrupt):
        checks_floor.main(["--repo", str(repo), "--base", "main"])


def _ordinary(repo: Path, change: str) -> None:
    if change == "source":
        write(repo, "src/app.py", "VALUE = 2\n")
    elif change == "test-added":
        write(repo, "tests/test_more.py", "def test_b():\n    assert True\n")
    elif change == "docs":
        write(repo, "docs/guide.md", "# Guide\n")
    elif change == "dependency":
        write(repo, "requirements.txt", "requests==2.32.3\n")
    elif change == "instructions":
        write(repo, "AGENTS.md", "# Rules\n")
    elif change == "rename-source":
        git(repo, "mv", "src/app.py", "src/core.py")
    commit(repo, change)


@pytest.mark.parametrize("change", ["source", "test-added", "docs", "dependency", "instructions", "rename-source"])
def test_ordinary_pull_request_passes(tmp_path, capsys, change):
    """V7. rename-source runs without the fixture's probe gate, which refuses every deletion by design."""
    repo = _base_without(tmp_path, "probe") if change == "rename-source" else base_repo(tmp_path)
    _ordinary(repo, change)
    code, out = run_floor(repo, capsys)
    assert code == 0, out


@pytest.mark.parametrize("dest", ["tests/test_main.py", "tests/unit/test_core.py"])
def test_renaming_or_moving_a_test_file_is_refused_as_a_deletion(tmp_path, capsys, dest):
    """L6, a stated cost: --no-renames reads the move as a deleted test file."""
    repo = _base_without(tmp_path, "probe")
    (repo / dest).parent.mkdir(parents=True, exist_ok=True)
    git(repo, "mv", "tests/test_core.py", dest)
    commit(repo, "move")
    code, out = run_floor(repo, capsys)
    assert code == 1, out
    assert "test-integrity" in out, out


def test_history_pass_reads_a_rename_as_a_delete_and_an_add(tmp_path, capsys):
    """L5: a secret moved in one commit and removed in the next is judged at the path it was added under."""
    repo = _base_without(tmp_path, "probe", "test-integrity")
    write(repo, "src/a.txt", "key = FLOOR-TOKEN-7\n")
    commit(repo, "add")
    git(repo, "mv", "src/a.txt", "src/b.txt")
    commit(repo, "move")
    git(repo, "rm", "-q", "src/b.txt")
    commit(repo, "drop")
    code, out = run_floor(repo, capsys)
    assert code == 1, out
    assert "src/a.txt" in out, out


def test_branch_that_merged_an_advanced_base_passes(tmp_path, capsys):
    repo = base_repo(tmp_path)
    write(repo, "src/feature.py", "X = 1\n")
    commit(repo, "pr work")
    git(repo, "checkout", "-q", "main")
    write(repo, ".github/workflows/chock.yml", "name: changed by a maintainer\n")
    commit(repo, "base advanced")
    git(repo, "checkout", "-q", "pr")
    git(repo, *_IDENT, "merge", "-q", "--no-edit", "main")
    code, out = run_floor(repo, capsys)
    assert code == 0, out


def test_merge_result_against_advanced_base_passes(tmp_path, capsys):
    repo = base_repo(tmp_path)
    write(repo, "src/feature.py", "X = 1\n")
    commit(repo, "pr work")
    git(repo, "checkout", "-q", "main")
    write(repo, ".github/workflows/chock.yml", "name: changed by a maintainer\n")
    write(repo, "tests/test_core.py", TEST_FILE.replace("    assert 2 * 2 == 4\n", ""))
    commit(repo, "base advanced (a maintainer trimmed a test)")
    git(repo, "checkout", "-q", "-b", "merge-ref")
    git(repo, *_IDENT, "merge", "-q", "--no-edit", "pr")
    code, out = run_floor(repo, capsys)
    assert code == 0, out


def _marker_py(marks: Path, name: str) -> str:
    return f"import pathlib\npathlib.Path({str(marks / name)!r}).write_text('ran')\n"


def _marker_sh(marks: Path, name: str) -> str:
    return f"#!/bin/sh\necho ran > {marks / name}\ncat\n"


@pytest.mark.parametrize("checkout", ["head", "base"])
def test_no_head_file_runs(tmp_path, capsys, checkout):
    marks = tmp_path / "marks"
    marks.mkdir()
    repo = base_repo(tmp_path)
    write(repo, PROBE["params"]["script"], _marker_py(marks, "head-probe"))
    write(repo, ".agents/policies/probe/implementations/sitecustomize.py", _marker_py(marks, "head-site-impl"))
    for rel, name in (("sitecustomize.py", "site"), ("usercustomize.py", "usersite"), ("json.py", "json")):
        write(repo, rel, _marker_py(marks, name))
    write(repo, ".chock/bin/gate.py", _marker_py(marks, "head-runner"))
    write(repo, ".chock/compiled/evil/ci-gate/gate.json",
          {"kind": "script", "on": ["commit"], "action": "block", "message": "m",
           "params": {"script": "evil.py"}, "script_base": "gate"})  # fmt: skip
    write(repo, ".chock/compiled/evil/ci-gate/evil.py", _marker_py(marks, "head-gate"))
    write(repo, ".gitattributes", "* diff=evil filter=evil\n")
    write(repo, "src/app.py", "VALUE = 2\n")
    write(repo, ".githooks/post-checkout", _marker_sh(marks, "hook"))
    commit(repo, "pr")
    args = ["--repo", str(repo), "--base", "main"]
    if checkout == "base":
        git(repo, "checkout", "-q", "main")
        args += ["--head", "pr"]
    for name in ("textconv", "diffcmd", "clean", "smudge", "process", "fsmonitor"):
        script = tmp_path / f"{name}.sh"
        script.write_text(_marker_sh(marks, name))
        script.chmod(0o755)
    for key, name in (("diff.evil.textconv", "textconv"), ("diff.evil.command", "diffcmd"),
                      ("filter.evil.clean", "clean"), ("filter.evil.smudge", "smudge"),
                      ("filter.evil.process", "process"), ("core.fsmonitor", "fsmonitor")):  # fmt: skip
        git(repo, "config", key, str(tmp_path / f"{name}.sh"))
    cwd = os.getcwd()
    os.chdir(repo)
    try:
        code = floor_main(args)
    finally:
        os.chdir(cwd)
    out = capsys.readouterr()
    assert sorted(p.name for p in marks.iterdir()) == [], out.out + out.err
    assert code == 1, out.out + out.err
