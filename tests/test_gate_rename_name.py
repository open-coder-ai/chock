"""A rename into a refused name is new work, even when the content is old, on a real git repository.

The toy script gate reports a finding for a path whose NAME matches a pattern (keyed by the name, as the
catalog's name gates key theirs) and another for a line whose CONTENT matches. Each case runs at commit, at
the turn's end and on the CI range. E-1's content rule is kept: a pure rename of an old content finding is allowed.
"""

from __future__ import annotations

import json
import subprocess
import textwrap
from collections.abc import Callable
from pathlib import Path

import pytest
from conftest import init_repo

from chock.gate.runner import run

PAD = "a = 1\nb = 2\nc = 3\nd = 4\n"
OLD = PAD + "x = BAD\n"
BASE = "trunk"
SCRIPT = "namegate.py"

#: A path whose basename holds `REFUSED` is a name finding, keyed by the path; a line holding BAD is a content finding.
TOY = textwrap.dedent(
    """\
    import json, sys
    payload = json.load(sys.stdin)
    found = []
    for path, text in payload["writes"].items():
        if "REFUSED" in path.rsplit("/", 1)[-1]:
            found.append({"key": "name|" + path, "path": path, "line": 1, "message": "refused name " + path})
        for number, line in enumerate(text.splitlines(), 1):
            if "BAD" in line:
                found.append({"key": "bad:" + line, "path": path, "line": number, "message": "bad " + line})
    print(json.dumps({"findings": found}))
    if found:
        print("RAW-STDERR", file=sys.stderr)
        sys.exit(1)
    """
)

Surface = Callable[[Path, Path, dict[str, str]], int]


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def _repo(tmp_path: Path, **head: str) -> Path:
    (tmp_path / "repo").mkdir()
    repo = init_repo(tmp_path / "repo")
    for rel, text in {**head, "keep.py": "k = 1\n"}.items():
        (repo / rel).write_text(text, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")
    _git(repo, "branch", "-M", BASE)
    (repo / SCRIPT).write_text(TOY, encoding="utf-8")
    gate = repo / "gate.json"
    spec = {"kind": "script", "on": ["commit", "tool_use"], "action": "block", "message": "m"}
    gate.write_text(json.dumps({**spec, "params": {"script": SCRIPT}}), encoding="utf-8")
    return repo


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


SURFACES = [
    pytest.param(_commit_surface, id="commit"),
    pytest.param(_stop_surface, id="stop"),
    pytest.param(_ci_surface, id="ci"),
]


def _mv(repo: Path, old: str, new: str, text: str) -> dict[str, str]:
    _git(repo, "mv", old, new)
    return {new: text}


@pytest.mark.parametrize("surface", SURFACES)
def test_a_pure_rename_from_a_clean_name_into_a_refused_name_is_refused(tmp_path: Path, surface: Surface) -> None:
    repo = _repo(tmp_path, **{"old.py": PAD})
    assert surface(repo / "gate.json", repo, _mv(repo, "old.py", "REFUSED.py", PAD)) == 1


@pytest.mark.parametrize("surface", SURFACES)
def test_a_rename_from_a_refused_name_to_another_refused_name_is_refused(tmp_path: Path, surface: Surface) -> None:
    repo = _repo(tmp_path, **{"REFUSED_a.py": PAD})
    assert surface(repo / "gate.json", repo, _mv(repo, "REFUSED_a.py", "REFUSED_b.py", PAD)) == 1


@pytest.mark.parametrize("surface", SURFACES)
def test_a_rename_from_a_refused_name_to_a_clean_name_is_allowed(tmp_path: Path, surface: Surface) -> None:
    repo = _repo(tmp_path, **{"REFUSED.py": PAD})
    assert surface(repo / "gate.json", repo, _mv(repo, "REFUSED.py", "clean.py", PAD)) == 0


@pytest.mark.parametrize("surface", SURFACES)
def test_a_pure_rename_of_a_file_whose_only_finding_is_content_is_allowed(tmp_path: Path, surface: Surface) -> None:
    repo = _repo(tmp_path, **{"old.py": OLD})
    assert surface(repo / "gate.json", repo, _mv(repo, "old.py", "new.py", OLD)) == 0


@pytest.mark.parametrize("surface", SURFACES)
def test_a_rename_that_adds_a_content_finding_is_refused_and_names_only_that_finding(
    tmp_path: Path, surface: Surface, capsys: pytest.CaptureFixture
) -> None:
    repo = _repo(tmp_path, **{"old.py": OLD})
    text = OLD + "y = BAD two\n"
    assert surface(repo / "gate.json", repo, _mv(repo, "old.py", "new.py", text)) == 1
    err = capsys.readouterr().err
    assert "new.py:6: bad y = BAD two" in err
    assert "x = BAD" not in err


@pytest.mark.parametrize("surface", SURFACES)
def test_a_rename_into_a_refused_name_names_the_name_and_not_the_old_content_finding(
    tmp_path: Path, surface: Surface, capsys: pytest.CaptureFixture
) -> None:
    repo = _repo(tmp_path, **{"old.py": OLD})
    assert surface(repo / "gate.json", repo, _mv(repo, "old.py", "REFUSED.py", OLD)) == 1
    err = capsys.readouterr().err
    assert "refused name REFUSED.py" in err
    assert "x = BAD" not in err
