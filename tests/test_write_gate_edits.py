"""An edit call is judged as the file it would leave, not as the fragment it carries.

Claude Code changes an existing file with Edit or MultiEdit, whose payload holds only the text
replaced and the text put in. Judged alone, that fragment has no imports, no class and no
neighbours, so a policy that reads whole files -- java-security's SQL rule, for one -- found
nothing in it, and the write went through: only the turn's Stop hook caught it. The first real
Claude Code run of the java-security agent kit (Windows) showed exactly that.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from chock.gate import edit_image, write_gate

REPO = "src/Repo.java"
BEFORE = "import db.Jdbc;\n\nclass Repo {\n    void all() {}\n}\n"
BAD = '    void by(String c) { jdbc.query("x = \'" + c + "\'"); }\n'
FRAGMENT_OLD = "    void all() {}\n"
FRAGMENT_NEW = FRAGMENT_OLD + BAD


def _edit(tool_input, path=REPO, name="pre_tool", content=None):
    raw = {"hook_event_name": "PreToolUse", "tool_name": "Edit", "tool_input": tool_input}
    return SimpleNamespace(event=name, path=path, content=content, raw=raw)


def _repo(tmp_path: Path, text: str = BEFORE, newline: str = "\n") -> Path:
    target = tmp_path / REPO
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8", newline=newline)
    return tmp_path


def _claude_edit(**extra):
    return _edit(
        {"file_path": REPO, "old_string": FRAGMENT_OLD, "new_string": FRAGMENT_NEW, **extra}, content=FRAGMENT_NEW
    )


# --- rebuilding the file ---------------------------------------------------------------------------


def test_an_edit_is_judged_as_the_whole_file_it_leaves(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    assert write_gate.writes_from_event(_claude_edit(), root) == {REPO: BEFORE.replace(FRAGMENT_OLD, FRAGMENT_NEW)}


def test_the_edit_fragment_alone_is_still_what_added_lines_means(tmp_path: Path) -> None:
    assert write_gate.added_from_event(_claude_edit()) == {REPO: FRAGMENT_NEW}


def test_replace_all_replaces_every_occurrence_and_the_default_the_first(tmp_path: Path) -> None:
    root = _repo(tmp_path, "a\na\n")
    once = _edit({"file_path": REPO, "old_string": "a", "new_string": "b"})
    every = _edit({"file_path": REPO, "old_string": "a", "new_string": "b", "replace_all": True})
    assert edit_image.edited_text(once, root) == "b\na\n"
    assert edit_image.edited_text(every, root) == "b\nb\n"


def test_a_multiedit_applies_its_edits_in_order(tmp_path: Path) -> None:
    root = _repo(tmp_path, "one\n")
    event = _edit(
        {
            "file_path": REPO,
            "edits": [{"old_string": "one", "new_string": "two"}, {"old_string": "two", "new_string": "three"}],
        }
    )
    assert edit_image.edited_text(event, root) == "three\n"
    assert edit_image.added_from_event(event) == {REPO: "two\nthree"}


@pytest.mark.parametrize(("old", "new"), [("oldString", "newString"), ("old_str", "new_str")])
def test_the_other_clients_spellings_are_edits_too(tmp_path: Path, old: str, new: str) -> None:
    root = _repo(tmp_path, "one\n")
    assert edit_image.edited_text(_edit({"filePath": REPO, old: "one", new: "two"}), root) == "two\n"


def test_a_tool_input_sent_as_a_json_string_is_read(tmp_path: Path) -> None:
    root = _repo(tmp_path, "one\n")
    event = _edit(json.dumps({"file_path": REPO, "old_string": "one", "new_string": "two"}))
    assert edit_image.edited_text(event, root) == "two\n"


def test_a_windows_crlf_file_is_edited_with_either_line_ending(tmp_path: Path) -> None:
    root = _repo(tmp_path, BEFORE, newline="\r\n")
    for old, new in [
        (FRAGMENT_OLD, FRAGMENT_NEW),
        (FRAGMENT_OLD.replace("\n", "\r\n"), FRAGMENT_NEW.replace("\n", "\r\n")),
    ]:
        event = _edit({"file_path": REPO, "old_string": old, "new_string": new})
        assert edit_image.edited_text(event, root) == BEFORE.replace(FRAGMENT_OLD, FRAGMENT_NEW)


def test_an_absolute_path_is_read_where_it_points(tmp_path: Path) -> None:
    _repo(tmp_path, "one\n")
    event = _edit(
        {"file_path": str(tmp_path / REPO), "old_string": "one", "new_string": "two"}, path=str(tmp_path / REPO)
    )
    assert edit_image.edited_text(event, Path("/nowhere")) == "two\n"


def test_an_empty_old_string_creates_a_file_that_is_not_there(tmp_path: Path) -> None:
    event = _edit({"file_path": "New.java", "old_string": "", "new_string": "class New {}\n"}, path="New.java")
    assert edit_image.edited_text(event, tmp_path) == "class New {}\n"


# --- when the file cannot be rebuilt, the fragment is judged as before ------------------------------


def test_text_that_is_not_in_the_file_falls_back_to_the_fragment(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    event = _edit({"file_path": REPO, "old_string": "absent", "new_string": BAD}, content=BAD)
    assert edit_image.edited_text(event, root) is None
    assert write_gate.writes_from_event(event, root) == {REPO: BAD}


def test_an_empty_old_string_on_an_existing_file_is_not_rebuilt(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    assert edit_image.edited_text(_edit({"file_path": REPO, "old_string": "", "new_string": "x"}), root) is None


def test_an_unreadable_file_falls_back_to_the_fragment(tmp_path: Path) -> None:
    (tmp_path / REPO).mkdir(parents=True)  # a directory where the file should be
    event = _edit({"file_path": REPO, "old_string": "a", "new_string": BAD}, content=BAD)
    assert write_gate.writes_from_event(event, tmp_path) == {REPO: BAD}


@pytest.mark.parametrize(
    "tool_input",
    [
        {"file_path": REPO, "content": "whole file"},
        {"file_path": REPO, "old_string": "a"},
        {"file_path": REPO, "edits": [{"old_string": "a", "new_string": "b"}, "not an edit"]},
        {"file_path": REPO, "edits": []},
        "{not json",
        "plain text",
    ],
)
def test_anything_that_is_not_an_edit_is_left_as_it_was(tmp_path: Path, tool_input) -> None:
    event = _edit(tool_input, content="whole file")
    assert edit_image.edit_replacements(event) is None
    assert write_gate.writes_from_event(event, tmp_path) == {REPO: "whole file"}
    assert write_gate.added_from_event(event) == {}


def test_an_edit_with_no_path_offers_nothing(tmp_path: Path) -> None:
    event = _edit({"old_string": "a", "new_string": "b"}, path=None)
    assert edit_image.edited_text(event, tmp_path) is None
    assert write_gate.added_from_event(event) == {}
    assert write_gate.writes_from_event(event, tmp_path) == {}


def test_a_relative_path_with_no_root_is_read_from_the_working_directory(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(_repo(tmp_path, "one\n"))
    assert edit_image.edited_text(_edit({"file_path": REPO, "old_string": "one", "new_string": "two"})) == "two\n"


# --- end to end, through the vendored runner ------------------------------------------------------


def _installed(root: Path, scan: str, pattern: str) -> Path:
    """A compiled content_regex gate and the vendored runner, laid out the way `chock sync` does."""
    spec = {
        "kind": "content_regex",
        "on": ["commit", "tool_use"],
        "action": "block",
        "message": "matched",
        "params": {"scan": scan, "content_pattern": pattern},
    }
    gate = root / ".chock" / "compiled" / "probe" / "pre-tool-use" / "gate.json"
    gate.parent.mkdir(parents=True)
    gate.write_text(json.dumps(spec), encoding="utf-8")
    runner = root / ".chock" / "bin" / "gate.py"
    runner.parent.mkdir(parents=True)
    source = Path(__file__).resolve().parents[1] / "src" / "chock" / "gate" / "runner.py"
    runner.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    return gate


def test_a_gate_reading_the_file_sees_what_the_fragment_leaves_out(tmp_path: Path) -> None:
    """The failure itself: the verdict needs a line the edit never touched."""
    root = _repo(tmp_path)
    gate = _installed(root, "staged_blob", r"^import db\.Jdbc;")
    decision = write_gate.evaluate_gate(["--gate", str(gate)], _claude_edit())
    assert decision is not None
    assert decision[0] == write_gate.VERDICT_DENY


def test_a_gate_reading_added_lines_still_sees_only_the_edit(tmp_path: Path) -> None:
    """Judging the whole file must not make a line already in the repository count as added."""
    root = _repo(tmp_path)
    assert (
        write_gate.evaluate_gate(["--gate", str(_installed(root, "added_lines", r"^import db"))], _claude_edit())
        is None
    )
    other = tmp_path / "other"
    _repo(other)
    decision = write_gate.evaluate_gate(
        ["--gate", str(_installed(other, "added_lines", r"jdbc\.query"))], _claude_edit()
    )
    assert decision is not None
    assert decision[0] == write_gate.VERDICT_DENY


def test_the_turns_end_still_judges_the_worktree_not_the_call(tmp_path: Path) -> None:
    gate = _installed(_repo(tmp_path), "staged_blob", r"^import db\.Jdbc;")
    stop = _claude_edit()
    stop.event = "stop"
    stop.raw = {"stop_hook_active": True}
    assert write_gate.evaluate_gate(["--gate", str(gate)], stop) is None
