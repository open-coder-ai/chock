"""Release gate G1, GT-1 attributes (S3), scenarios C1-C3: each test asserts the exit the plan owes.

Every git call the floor makes reads attributes from the base, so a `.gitattributes` the head adds changes nothing
the floor sees, and is not itself listed."""

from __future__ import annotations

import os
import shutil

import pytest
from floor_support import base_repo, commit, git, run_floor, write
from floor_support4 import raw_commit, rebase_main

VIOLATION = "VALUE = 'FLOOR-TOKEN-7'\n"
C1_ATTRIBUTES = ("-diff", "binary", "filter=x", "diff=x", "eol=crlf", "working-tree-encoding=UTF-16", "export-ignore")
C1_PLACES = {"root": (".gitattributes", "src/bad.py"), "nested": ("src/.gitattributes", "bad.py")}


@pytest.mark.parametrize("place", list(C1_PLACES))
@pytest.mark.parametrize("attribute", C1_ATTRIBUTES)
def test_c1_head_gitattributes_cannot_hide_a_content_violation(tmp_path, capsys, attribute, place):
    attrs, pattern = C1_PLACES[place]
    repo = base_repo(tmp_path)
    write(repo, "src/bad.py", VIOLATION)
    commit(repo, "pr: a violation")  # staged before the attributes exist, so no filter rewrites the blob
    write(repo, attrs, f"{pattern} {attribute}\n")
    git(repo, "add", attrs)  # by path: `add -A` would re-read bad.py through the new attribute
    raw_commit(repo, f"pr: mark it {attribute}")
    code, out = run_floor(repo, capsys)
    assert code == 1, (attribute, place, out)
    assert "floor-token" in out, out
    assert f"\n  {attrs}\n" not in out, out


@pytest.mark.parametrize("attribute", ["-diff", "binary"])
def test_c2_base_gitattributes_marking_a_path_never_hides_a_violation_there(tmp_path, capsys, attribute):
    repo = base_repo(tmp_path)
    rebase_main(repo, lambda r: write(r, ".gitattributes", f"src/** {attribute}\n"))
    write(repo, "src/bad.py", VIOLATION)
    commit(repo, "pr: a violation under a base attribute")
    code, out = run_floor(repo, capsys)
    assert code == 1, (attribute, out)
    assert "floor-token" in out, out


def test_c3_git_without_the_attribute_source_option_is_2_naming_the_version(tmp_path, capsys, monkeypatch):
    """A `git` wrapper earlier on PATH that drops GIT_ATTR_SOURCE, as a git older than 2.42 ignores it."""
    repo = base_repo(tmp_path)
    real = shutil.which("git")
    bin_dir = tmp_path / "old-git"
    bin_dir.mkdir()
    wrapper = bin_dir / "git"
    wrapper.write_text(f'#!/bin/sh\nunset GIT_ATTR_SOURCE\nexec "{real}" "$@"\n', encoding="utf-8")
    wrapper.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    assert shutil.which("git") == str(wrapper)
    write(repo, "src/app.py", "VALUE = 2\n")
    commit(repo, "pr: ordinary")
    code, out = run_floor(repo, capsys)
    assert code == 2, out
    assert "git 2.42 or newer" in out, out
