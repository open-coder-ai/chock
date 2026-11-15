"""A file git reports as renamed is judged against its old path's content, on a real git repository.

A pure `git mv` of a file holding an old finding adds nothing; a copy (old path kept) is new work.
Each case runs for a script gate and a `content_regex` gate, at commit, at the turn's end and on the CI range.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest
from conftest import write_gate
from findings_support import make_gate, repo_with

from chock.gate.runner import run

PAD = "a = 1\nb = 2\nc = 3\nd = 4\n"
OLD = PAD + "x = BAD\n"
BASE = "trunk"
REGEX = {"kind": "content_regex", "on": ["commit", "tool_use"], "action": "block", "message": "m"}
REGEX["params"] = {"scan": "added_lines", "content_pattern": "BAD"}

Gate = Callable[[Path, Path], Path]
Surface = Callable[[Path, Path, dict[str, str]], int]


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def _script_gate(repo: Path, _tmp: Path) -> Path:
    return make_gate(repo)


def _regex_gate(_repo: Path, tmp: Path) -> Path:
    return write_gate(tmp, REGEX)


def _put(repo: Path, files: dict[str, str]) -> None:
    for rel, text in files.items():
        (repo / rel).write_text(text, encoding="utf-8")


def _commit_surface(gate: Path, repo: Path, files: dict[str, str]) -> int:
    _put(repo, files)
    _git(repo, "add", "-A", "--", *files)
    return run(gate, "commit", None, repo)


def _stop_surface(gate: Path, repo: Path, files: dict[str, str]) -> int:
    _put(repo, files)
    return run(gate, "stop", None, repo, writes=files)


def _ci_surface(gate: Path, repo: Path, files: dict[str, str]) -> int:
    _git(repo, "checkout", "-q", "-b", "feature")
    _put(repo, files)
    _git(repo, "add", "-A", "--", *files)
    _git(repo, "commit", "-qm", "move")
    return run(gate, "ci", None, repo, base=BASE)


def _start(tmp_path: Path) -> Path:
    repo = repo_with(tmp_path, **{"old.py": OLD, "keep.py": "k = 1\n"})
    _git(repo, "branch", "-M", BASE)
    return repo


def _move(repo: Path, text: str | None, *, copy: bool = False) -> dict[str, str]:
    """Move (or copy) old.py to new.py, returning the new file's text for the surface to judge."""
    if copy:
        (repo / "new.py").write_text(OLD, encoding="utf-8")
        _git(repo, "add", "new.py")
    else:
        _git(repo, "mv", "old.py", "new.py")
    return {"new.py": OLD if text is None else text}


GATES = [pytest.param(_script_gate, id="script"), pytest.param(_regex_gate, id="content_regex")]
SURFACES = [
    pytest.param(_commit_surface, id="commit"),
    pytest.param(_stop_surface, id="stop"),
    pytest.param(_ci_surface, id="ci"),
]


@pytest.mark.parametrize("surface", SURFACES)
@pytest.mark.parametrize("make", GATES)
def test_a_pure_rename_of_an_old_finding_is_allowed(tmp_path: Path, make: Gate, surface: Surface) -> None:
    repo = _start(tmp_path)
    gate = make(repo, tmp_path)
    assert surface(gate, repo, _move(repo, None)) == 0


@pytest.mark.parametrize("surface", SURFACES)
@pytest.mark.parametrize("make", GATES)
def test_a_rename_that_adds_a_finding_refuses_the_new_one(tmp_path: Path, make: Gate, surface: Surface) -> None:
    repo = _start(tmp_path)
    gate = make(repo, tmp_path)
    assert surface(gate, repo, _move(repo, OLD + "y = BAD two\n")) == 1


@pytest.mark.parametrize("surface", SURFACES)
@pytest.mark.parametrize("make", GATES)
def test_a_rename_that_removes_a_finding_is_allowed(tmp_path: Path, make: Gate, surface: Surface) -> None:
    repo = _start(tmp_path)
    gate = make(repo, tmp_path)
    assert surface(gate, repo, _move(repo, PAD + "x = 1\n")) == 0


@pytest.mark.parametrize("surface", SURFACES)
@pytest.mark.parametrize("make", GATES)
def test_a_copy_with_the_old_path_kept_is_judged_as_new(tmp_path: Path, make: Gate, surface: Surface) -> None:
    repo = _start(tmp_path)
    gate = make(repo, tmp_path)
    assert surface(gate, repo, _move(repo, None, copy=True)) == 1


@pytest.mark.parametrize("surface", SURFACES)
def test_the_script_gate_names_only_the_added_finding_after_a_rename(
    tmp_path: Path, surface: Surface, capsys: pytest.CaptureFixture
) -> None:
    repo = _start(tmp_path)
    assert surface(make_gate(repo), repo, _move(repo, OLD + "y = BAD two\n")) == 1
    err = capsys.readouterr().err
    assert "new.py:6: bad y = BAD two" in err
    assert "x = BAD" not in err
