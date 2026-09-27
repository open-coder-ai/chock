"""A Codex apply_patch call is judged as the files it would leave.

Codex CLI writes with one tool, apply_patch, whose only argument is the patch text in
`tool_input.command` -- no path, no content -- so the write gate had nothing to judge before the
write and Codex was checked only at the turn's end. The patch is Codex's documented format; each
file it adds or updates is now rebuilt from the file on disk and judged whole.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from chock.gate import patch_image, write_gate

REPO = "src/Repo.java"
BEFORE = "import db.Jdbc;\n\nclass Repo {\n    void all() {}\n}\n"
BAD = '    void by(String c) { jdbc.query("x = \'" + c + "\'"); }'
UPDATE = f"""*** Begin Patch
*** Update File: {REPO}
@@ class Repo {{
     void all() {{}}
+{BAD}
 }}
*** End Patch"""


def _codex(command, name="pre_tool"):
    raw = {
        "hook_event_name": "PreToolUse",
        "turn_id": "t",
        "tool_name": "apply_patch",
        "tool_input": {"command": command},
    }
    return SimpleNamespace(event=name, path=None, content=None, raw=raw)


def _repo(tmp_path: Path, text: str = BEFORE) -> Path:
    (tmp_path / REPO).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / REPO).write_text(text, encoding="utf-8")
    return tmp_path


AFTER = BEFORE.replace("    void all() {}\n", "    void all() {}\n" + BAD + "\n")


# --- reading the patch -----------------------------------------------------------------------------


def test_an_update_is_judged_as_the_whole_file_it_leaves(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    assert write_gate.writes_from_event(_codex(UPDATE), root) == {REPO: AFTER}


def test_added_lines_are_only_the_lines_the_patch_adds() -> None:
    assert write_gate.added_from_event(_codex(UPDATE)) == {}
    assert patch_image.patch_added(_codex(UPDATE)) == {REPO: BAD}


@pytest.mark.parametrize(
    "command",
    [
        ["apply_patch", UPDATE],
        f"apply_patch <<'EOF'\n{UPDATE}\nEOF\n",
        UPDATE.replace("\n", "\r\n"),
    ],
)
def test_the_patch_is_found_however_the_command_carries_it(tmp_path: Path, command) -> None:
    assert patch_image.patched_files(_codex(command), _repo(tmp_path)) == {REPO: AFTER}


def test_a_new_file_is_its_added_lines(tmp_path: Path) -> None:
    patch = "*** Begin Patch\n*** Add File: New.java\n+class New {\n+}\n*** End Patch"
    assert patch_image.patched_files(_codex(patch), tmp_path) == {"New.java": "class New {\n}\n"}
    assert patch_image.patch_added(_codex(patch)) == {"New.java": "class New {\n}"}


def test_several_files_hunks_a_move_and_a_delete(tmp_path: Path) -> None:
    root = _repo(tmp_path, "a\nb\nc\nd\n")
    (root / "gone.txt").write_text("x\n", encoding="utf-8")
    patch = f"""*** Begin Patch
*** Update File: {REPO}
*** Move to: src/Moved.java
@@
-a
+A
@@
 c
-d
+D
*** Delete File: gone.txt
*** Add File: extra.txt
+hi
*** End Patch"""
    assert patch_image.patched_files(_codex(patch), root) == {"src/Moved.java": "A\nb\nc\nD\n", "extra.txt": "hi\n"}


def test_a_hunk_with_no_header_and_context_as_bare_lines(tmp_path: Path) -> None:
    patch = f"*** Begin Patch\n*** Update File: {REPO}\n a\n-b\n+B\n*** End Patch"
    assert patch_image.patched_files(_codex(patch), _repo(tmp_path, "a\nb\n")) == {REPO: "a\nB\n"}


def test_an_addition_at_the_end_of_the_file(tmp_path: Path) -> None:
    patch = f"*** Begin Patch\n*** Update File: {REPO}\n@@\n+z\n*** End of File\n*** End Patch"
    assert patch_image.patched_files(_codex(patch), _repo(tmp_path, "a\n")) == {REPO: "a\nz\n"}


def test_trailing_space_in_the_file_does_not_stop_a_hunk_placing(tmp_path: Path) -> None:
    patch = f"*** Begin Patch\n*** Update File: {REPO}\n-a\n+A\n*** End Patch"
    assert patch_image.patched_files(_codex(patch), _repo(tmp_path, "a  \n")) == {REPO: "A\n"}


def test_an_anchor_that_is_only_part_of_a_line_still_places_the_hunk(tmp_path: Path) -> None:
    patch = (
        f"*** Begin Patch\n*** Update File: {REPO}\n@@ Repo\n-    void all() {{}}\n+    void none() {{}}\n*** End Patch"
    )
    assert patch_image.patched_files(_codex(patch), _repo(tmp_path)) == {REPO: BEFORE.replace("all", "none")}


# --- when a file cannot be rebuilt, it is left to the turn's end ----------------------------------------


@pytest.mark.parametrize(
    "patch",
    [
        f"*** Begin Patch\n*** Update File: {REPO}\n-absent\n+x\n*** End Patch",
        f"*** Begin Patch\n*** Update File: {REPO}\n@@ no such anchor\n-a\n+x\n*** End Patch",
        "*** Begin Patch\n*** Update File: missing.java\n-a\n+x\n*** End Patch",
    ],
)
def test_a_hunk_that_cannot_be_placed_leaves_the_file_out(tmp_path: Path, patch: str) -> None:
    assert patch_image.patched_files(_codex(patch), _repo(tmp_path)) == {}


@pytest.mark.parametrize(
    "command", ["ls -la", "*** Begin Patch with no end", 42, None, "*** End of File\n*** End Patch\n*** Begin Patch"]
)
def test_anything_that_is_not_a_patch_is_left_alone(tmp_path: Path, command) -> None:
    event = _codex(command)
    assert patch_image.patched_files(event, tmp_path) == {}
    assert patch_image.patch_added(event) == {}
    assert write_gate.writes_from_event(event, tmp_path) == {}


def test_lines_before_the_first_file_and_an_end_of_file_marker_with_no_hunk_are_ignored() -> None:
    patch = f"*** Begin Patch\nstray\n*** Update File: {REPO}\n*** End of File\n*** End Patch"
    assert patch_image.parse_patch(patch) == [("update", REPO, None, [])]


def test_a_payload_with_no_tool_input_is_not_a_patch() -> None:
    event = SimpleNamespace(event="pre_tool", path=None, content=None, raw={"tool_name": "apply_patch"})
    assert patch_image.patch_text(event) is None


def test_a_relative_path_with_no_root_is_read_from_the_working_directory(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(_repo(tmp_path))
    assert patch_image.patched_files(_codex(UPDATE)) == {REPO: AFTER}


def test_an_absolute_path_is_read_where_it_points(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    patch = UPDATE.replace(REPO, str(root / REPO))
    assert patch_image.patched_files(_codex(patch), Path("/nowhere")) == {str(root / REPO): AFTER}


# --- end to end, through the vendored runner ------------------------------------------------------


def _installed(root: Path, scan: str, pattern: str) -> Path:
    spec = {"kind": "content_regex", "on": ["commit", "tool_use"], "action": "block", "message": "matched"}
    spec["params"] = {"scan": scan, "content_pattern": pattern}
    gate = root / ".chock" / "compiled" / "probe" / "pre-tool-use" / "gate.json"
    gate.parent.mkdir(parents=True)
    gate.write_text(json.dumps(spec), encoding="utf-8")
    runner = root / ".chock" / "bin" / "gate.py"
    runner.parent.mkdir(parents=True)
    source = Path(__file__).resolve().parents[1] / "src" / "chock" / "gate" / "runner.py"
    runner.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    return gate


def test_a_gate_reading_the_file_sees_what_the_patch_leaves_out(tmp_path: Path) -> None:
    gate = _installed(_repo(tmp_path), "staged_blob", r"^import db\.Jdbc;")
    decision = write_gate.evaluate_gate(["--gate", str(gate)], _codex(UPDATE))
    assert decision is not None
    assert decision[0] == write_gate.VERDICT_DENY


def test_a_gate_reading_added_lines_sees_only_what_the_patch_adds(tmp_path: Path) -> None:
    gate = _installed(_repo(tmp_path), "added_lines", r"^import db")
    assert write_gate.evaluate_gate(["--gate", str(gate)], _codex(UPDATE)) is None


def test_parsing_stops_at_the_text_end_when_there_is_no_end_marker() -> None:
    assert patch_image.parse_patch("*** Begin Patch\n*** Add File: a.txt\n+x") == [("add", "a.txt", None, ["x"])]


def test_a_deleted_file_adds_no_lines() -> None:
    patch = "*** Begin Patch\n*** Delete File: gone.txt\n*** Add File: a.txt\n+x\n*** End Patch"
    assert patch_image.patch_added(_codex(patch)) == {"a.txt": "x"}
