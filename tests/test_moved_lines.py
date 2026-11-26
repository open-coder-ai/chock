"""A line the change only moves, or re-indents, is not one it adds; a copy or an edited line still is."""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from conftest import init_repo, write_gate
from floor_support import base_repo, commit, run_floor, write
from floor_support import gate as floor_gate

from chock.gate import edit_image, patch_image
from chock.gate.runner import WriteContext, run
from chock.gate.runner.gitparse import cancel_moved

TOKEN = "FLOOR-TOKEN-1"
ONE = f"def one():\n    t = '{TOKEN}'\n    return t\n"
TWO = "def two():\n    return 2\n"
SPACED = f"def spaced():\n    if True:\n        t = '{TOKEN}'\n    return t\n"
REINDENTED = f"def spaced():\n  if True:\n    t = '{TOKEN}'\n  return t\n"
PATH = "src/mod.py"
OTHER = "src/other.py"

#: name -> (files before, files after, whether the change adds the token again)
CASES = {
    "moved_within_file": ({PATH: f"{ONE}\n\n{TWO}"}, {PATH: f"{TWO}\n\n{ONE}"}, False),
    "moved_to_another_file": (
        {PATH: f"{ONE}\n\n{TWO}", OTHER: "x = 1\n"},
        {PATH: TWO, OTHER: f"x = 1\n\n{ONE}"},
        True,
    ),
    "reindented_file": ({PATH: SPACED}, {PATH: REINDENTED}, False),
    "copy_keeps_the_original": ({PATH: f"{ONE}\n\n{TWO}"}, {PATH: f"{ONE}\n\n{TWO}\n\n{ONE}"}, True),
    "moved_and_edited": (
        {PATH: f"{ONE}\n\n{TWO}"},
        {PATH: f"{TWO}\n\n{ONE.replace('FLOOR-TOKEN-1', 'FLOOR-TOKEN-2')}"},
        True,
    ),
    "inner_whitespace_counts": ({PATH: f"{ONE}\n"}, {PATH: ONE.replace("t = '", "t  = '") + "\n"}, True),
}
IDS = list(CASES)


def _gate(tmp_path: Path) -> Path:
    tmp_path.mkdir(exist_ok=True)
    params = {"content_pattern": "FLOOR-TOKEN-[0-9]+"}
    return write_gate(
        tmp_path,
        {"kind": "content_regex", "on": ["commit", "tool_use"], "action": "block", "message": "m", "params": params},
    )


@pytest.mark.parametrize("case", IDS)
def test_commit_judges_only_what_the_change_adds(tmp_path: Path, case: str) -> None:
    before, after, adds = CASES[case]
    gate = _gate(tmp_path / "gate")
    (tmp_path / "repo").mkdir()
    repo = init_repo(tmp_path / "repo")
    for rel, text in before.items():
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(text, encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=repo, check=True)
    for rel, text in after.items():
        (repo / rel).write_text(text, encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    assert run(gate, "pre-commit", None, repo) == (1 if adds else 0)


@pytest.mark.parametrize("case", IDS)
def test_the_floor_judges_only_what_the_change_adds(tmp_path: Path, capsys, case: str) -> None:
    before, after, adds = CASES[case]
    repo = base_repo(tmp_path)
    for rel, text in before.items():
        write(repo, rel, text)
    seed = commit(repo, "seed")
    for rel, text in after.items():
        write(repo, rel, text)
    commit(repo, "change")
    code, out = run_floor(repo, capsys, "--base", seed)
    assert ("FAIL floor-token [base]" in out) == adds, out
    assert code == (1 if "FAIL" in out else 0), out


def _edit_event(path: str, old: str, new: str) -> SimpleNamespace:
    raw = {"tool_name": "Edit", "tool_input": {"file_path": path, "old_string": old, "new_string": new}}
    return SimpleNamespace(event="pre_tool", path=path, content=new, raw=raw)


@pytest.mark.parametrize(
    "case", ["moved_within_file", "reindented_file", "copy_keeps_the_original", "moved_and_edited"]
)
def test_an_agent_edit_adds_only_what_old_string_lacks(case: str) -> None:
    before, after, adds = CASES[case]
    old, new = before[PATH], after[PATH]
    got = edit_image.added_from_event(_edit_event(PATH, old, new)).get(PATH, "")
    assert (TOKEN in got or "FLOOR-TOKEN-2" in got) == adds


@pytest.mark.parametrize(
    "case", ["moved_within_file", "reindented_file", "copy_keeps_the_original", "moved_and_edited"]
)
def test_an_agent_write_adds_only_what_the_file_lacked(tmp_path: Path, case: str) -> None:
    before, after, adds = CASES[case]
    (tmp_path / "repo").mkdir()
    repo = init_repo(tmp_path / "repo")
    (repo / "src").mkdir()
    (repo / PATH).write_text(before[PATH], encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=repo, check=True)
    gate = _gate(tmp_path / "gate")
    assert run(gate, "pre-tool-use", None, repo, writes={PATH: after[PATH]}) == (1 if adds else 0)


def test_an_agent_edit_through_the_gate_judges_the_edit(tmp_path: Path) -> None:
    before, after, _ = CASES["moved_within_file"]
    (tmp_path / "repo").mkdir()
    repo = init_repo(tmp_path / "repo")
    (repo / "src").mkdir()
    (repo / PATH).write_text(before[PATH], encoding="utf-8")
    added = edit_image.added_from_event(_edit_event(PATH, before[PATH], after[PATH]))
    gate = _gate(tmp_path / "gate")
    assert run(gate, "pre-tool-use", None, repo, writes={PATH: after[PATH]}, added=added) == 0


def test_a_patch_moves_a_line_without_adding_it() -> None:
    patch = (
        "*** Begin Patch\n*** Update File: src/mod.py\n@@\n"
        f"-    t = '{TOKEN}'\n     return t\n+    t = '{TOKEN}'\n*** End Patch\n"
    )
    event = SimpleNamespace(
        event="pre_tool", path=PATH, content=None, raw={"tool_name": "apply_patch", "tool_input": patch}
    )
    assert TOKEN not in patch_image.patch_added(event).get(PATH, "")


def test_each_removed_line_cancels_one_added_line() -> None:
    assert cancel_moved(["a", "  a ", "b"], ["a"]) == (["  a ", "b"], [])


def test_a_write_context_keeps_a_copy(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    (repo / "m.py").write_text("a = 1\n", encoding="utf-8")
    ctx = WriteContext(repo, {"m.py": "a = 1\na = 1\n"})
    assert ctx.added_lines("m.py") == ["a = 1"]


def _commit_all(repo: Path, message: str = "base") -> None:
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", message], cwd=repo, check=True)


def _repo(tmp_path: Path, files: dict[str, str]) -> Path:
    (tmp_path / "repo").mkdir()
    repo = init_repo(tmp_path / "repo")
    for rel, text in files.items():
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(text, encoding="utf-8")
    _commit_all(repo)
    return repo


ASSERTED = "def test_a():\n    assert result == expected\n    assert other == 1\n"


def test_an_assert_moved_out_of_a_test_file_is_still_a_removal(tmp_path: Path) -> None:
    repo = _repo(tmp_path, {"tests/test_x.py": ASSERTED, "notes/old.md": "notes\n"})
    (repo / "tests/test_x.py").write_text("def test_a():\n    assert other == 1\n", encoding="utf-8")
    (repo / "notes/old.md").write_text("notes\n    assert result == expected\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    params = {"test_path_regex": "(^|/)tests?/", "assertion_pattern": r"\bassert\b"}
    spec = {"kind": "test_integrity", "on": ["commit"], "action": "block", "message": "m", "params": params}
    (tmp_path / "gate").mkdir()
    assert run(write_gate(tmp_path / "gate", spec), "pre-commit", None, repo) == 1


UNPINNED = "      - uses: actions/checkout@v4\n"
WORKFLOW_SPEC = {
    "kind": "content_regex",
    "on": ["commit"],
    "action": "block",
    "message": "pin it",
    "paths": [".github/workflows/*"],
    "params": {"content_pattern": r"uses: \S+@v\d"},
}
BEFORE = {"docs/example.md": f"steps:\n{UNPINNED}", ".github/workflows/ci.yml": "name: ci\n"}


def test_an_unpinned_uses_line_moved_into_a_workflow_is_still_refused_at_commit(tmp_path: Path) -> None:
    repo = _repo(tmp_path, BEFORE)
    (repo / "docs/example.md").write_text("steps:\n", encoding="utf-8")
    (repo / ".github/workflows/ci.yml").write_text(f"name: ci\n{UNPINNED}", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    (tmp_path / "gate").mkdir()
    assert run(write_gate(tmp_path / "gate", WORKFLOW_SPEC), "pre-commit", None, repo) == 1


def test_a_line_moved_into_a_path_scoped_policys_files_is_still_refused_at_the_floor(tmp_path: Path, capsys) -> None:
    """The floor treats `.github/workflows` as control plane, so the scoped files here are `deploy/*`."""
    repo = base_repo(tmp_path)
    floor_gate(repo, "pin-uses", {**WORKFLOW_SPEC, "paths": ["deploy/*"]})
    write(repo, "docs/example.md", f"steps:\n{UNPINNED}")
    write(repo, "deploy/run.yml", "name: run\n")
    seed = commit(repo, "seed")
    write(repo, "docs/example.md", "steps:\n")
    write(repo, "deploy/run.yml", f"name: run\n{UNPINNED}")
    commit(repo, "move")
    _, out = run_floor(repo, capsys, "--base", seed)
    assert "FAIL pin-uses [base]" in out, out


def test_a_renamed_and_re_indented_file_is_one_file_at_commit(tmp_path: Path) -> None:
    top = "".join(f"line_{n} = {n}\n" for n in range(30))
    old = f"{top}def spaced():\n    if True:\n        t = '{TOKEN}'\n"
    new = f"{top}def spaced():\n  if True:\n    t = '{TOKEN}'\n"
    repo = _repo(tmp_path, {"old.py": old})
    subprocess.run(["git", "mv", "old.py", "new.py"], cwd=repo, check=True)
    (repo / "new.py").write_text(new, encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    (tmp_path / "gate").mkdir()
    assert run(_gate(tmp_path / "gate"), "pre-commit", None, repo) == 0
