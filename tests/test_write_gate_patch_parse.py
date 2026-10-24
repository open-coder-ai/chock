"""An apply_patch text is read the way Codex reads it, so nothing it writes escapes the write gate.

Every payload here was run through Codex CLI 0.162.1's own apply_patch: each one it accepts
writes the probe token (or a file under secret/), and each expected text below is the bytes
it wrote. Before GAP-3e the gate allowed all of them except where noted.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from chock.gate import patch_image, write_gate
from chock.gate.assemble import runner_source

TOKEN = "probe-token-3e"


def _patch(body: str) -> str:
    return f"*** Begin Patch\n{body}\n*** End Patch"


def _event(command, cwd: Path | None = None):
    raw = {
        "hook_event_name": "PreToolUse",
        "turn_id": "t",
        "tool_name": "apply_patch",
        "tool_input": {"command": command},
    }
    return SimpleNamespace(event="pre_tool", path=None, content=None, raw=raw, cwd=str(cwd) if cwd else None)


def _files(root: Path, files: dict[str, str]) -> Path:
    for path, text in files.items():
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_bytes(text.encode("utf-8"))
    return root


def _gate(root: Path, params: dict) -> Path:
    spec = {"kind": "content_regex", "on": ["commit", "tool_use"], "action": "block", "message": "matched"}
    gate = root / ".chock" / "compiled" / "probe" / "pre-tool-use" / "gate.json"
    gate.parent.mkdir(parents=True)
    gate.write_text(json.dumps({**spec, "params": params}), encoding="utf-8")
    runner = root / ".chock" / "bin" / "gate.py"
    runner.parent.mkdir(parents=True)
    runner.write_text(runner_source(), encoding="utf-8")
    return gate


CONTENT = {"scan": "staged_blob", "content_pattern": TOKEN}
SECRET_PATH = {"content_pattern": "(?!)", "forbidden_path_regex": r"(^|/)secret/"}

#: (on disk, patch, agent's working directory under the root, gate params)
WRITTEN = {
    "an add whose content line is '+*** End Patch'": (
        {},
        _patch(f"*** Add File: a.txt\n+*** End Patch\n+{TOKEN}"),
        "",
        CONTENT,
    ),
    "an update whose added line holds '*** End Patch'": (
        {"f.txt": "a\n"},
        _patch(f"*** Update File: f.txt\n@@\n a\n+x *** End Patch y\n+{TOKEN}"),
        "",
        CONTENT,
    ),
    "a delete then an indented Add File header": (
        {"old.txt": "o\n"},
        _patch(f"*** Delete File: old.txt\n *** Add File: n.txt\n+{TOKEN}"),
        "",
        CONTENT,
    ),
    "an add then a no-break-space Add File header": (
        {},
        _patch("*** Add File: a.txt\n+ok\n\xa0*** Add File: secret/x.txt\n+hi"),
        "",
        SECRET_PATH,
    ),
    "context that matches only with both ends trimmed": (
        {"f.txt": "    keep\n"},
        _patch(f"*** Update File: f.txt\n@@\n keep\n+{TOKEN}"),
        "",
        CONTENT,
    ),
    "context with an en dash written as '-'": (
        {"f.txt": "a \u2013 b\n"},
        _patch(f"*** Update File: f.txt\n@@\n a - b\n+{TOKEN}"),
        "",
        CONTENT,
    ),
    "an anchor with curly quotes written straight": (
        {"f.txt": "say \u201chi\u201d\nz\n"},
        _patch(f'*** Update File: f.txt\n@@ say "hi"\n z\n+{TOKEN}'),
        "",
        CONTENT,
    ),
    "a trailing blank context line on a file with no final newline": (
        {"f.txt": "x\ny"},
        _patch(f"*** Update File: f.txt\n@@\n y\n+{TOKEN}\n "),
        "",
        CONTENT,
    ),
    "an update in the agent's subdirectory": (
        {"sub/f.txt": "a\n"},
        _patch(f"*** Update File: f.txt\n@@\n a\n+{TOKEN}"),
        "sub",
        CONTENT,
    ),
    "an add in the agent's subdirectory": ({}, _patch("*** Add File: x.txt\n+hi"), "secret", SECRET_PATH),
    "an add then an update of the same file": (
        {},
        _patch(f"*** Add File: f.txt\n+a\n*** Update File: f.txt\n@@\n a\n+{TOKEN}"),
        "",
        CONTENT,
    ),
    "an update moved to a file a later update changes": (
        {"f.txt": "a\n"},
        _patch(f"*** Update File: f.txt\n*** Move to: g.txt\n@@\n-a\n+b\n*** Update File: g.txt\n@@\n b\n+{TOKEN}"),
        "",
        CONTENT,
    ),
    # Allowed before too; kept as regressions.
    "a plain add": ({}, _patch(f"*** Add File: a.txt\n+{TOKEN}"), "", CONTENT),
    "a CR-only file": ({"f.txt": "x\ry\r"}, _patch(f"*** Update File: f.txt\n@@\n y\n+{TOKEN}"), "", CONTENT),
    "an add after an End of File hunk": (
        {"f.txt": "a\n"},
        _patch(f"*** Update File: f.txt\n@@\n a\n+z\n*** End of File\n*** Add File: b.txt\n+{TOKEN}"),
        "",
        CONTENT,
    ),
    "an added '+@@' line": ({}, _patch(f"*** Add File: a.txt\n+@@ x\n+{TOKEN}"), "", CONTENT),
    "an added '+*** Add File:' line": (
        {"f.txt": "a\n"},
        _patch(f"*** Update File: f.txt\n@@\n a\n+*** Add File: q\n+{TOKEN}"),
        "",
        CONTENT,
    ),
    "\\x1c, \\x85 and U+2028 inside an added line": (
        {},
        _patch(f"*** Add File: a.txt\n+a\x1cb\x85c\u2028{TOKEN}"),
        "",
        CONTENT,
    ),
    "a pure addition after an anchor": (
        {"f.txt": "a\nb\n"},
        _patch(f"*** Update File: f.txt\n@@ a\n+{TOKEN}"),
        "",
        CONTENT,
    ),
}


@pytest.mark.parametrize("name", list(WRITTEN))
def test_what_codex_writes_is_judged(tmp_path: Path, name: str) -> None:
    files, patch, sub, params = WRITTEN[name]
    root = _files(tmp_path, files)
    (root / sub).mkdir(parents=True, exist_ok=True)
    gate = _gate(root, params)
    decision = write_gate.evaluate_gate(["--gate", str(gate)], _event(patch, root / sub))
    assert decision is not None
    assert decision[0] == write_gate.VERDICT_DENY
    assert "matched" in decision[1]


#: name in WRITTEN -> {path under the root: the bytes Codex wrote}
CODEX_WROTE = {
    "an update whose added line holds '*** End Patch'": {"f.txt": f"a\nx *** End Patch y\n{TOKEN}\n"},
    "context that matches only with both ends trimmed": {"f.txt": f"    keep\n{TOKEN}\n"},
    "context with an en dash written as '-'": {"f.txt": f"a \u2013 b\n{TOKEN}\n"},
    "an anchor with curly quotes written straight": {"f.txt": f"say \u201chi\u201d\nz\n{TOKEN}\n"},
    "a trailing blank context line on a file with no final newline": {"f.txt": f"x\ny\n{TOKEN}\n"},
    "a CR-only file": {"f.txt": f"x\ry\r{TOKEN}\r"},
    "an update in the agent's subdirectory": {"sub/f.txt": f"a\n{TOKEN}\n"},
    "a pure addition after an anchor": {"f.txt": f"a\nb\n{TOKEN}\n"},
    "an add then an update of the same file": {"f.txt": f"a\n{TOKEN}\n"},
    "an update moved to a file a later update changes": {"f.txt": "", "g.txt": f"b\n{TOKEN}\n"},
}


@pytest.mark.parametrize("name", list(CODEX_WROTE))
def test_each_file_is_rebuilt_as_codex_writes_it(tmp_path: Path, name: str) -> None:
    files, patch, sub, _ = WRITTEN[name]
    root = _files(tmp_path, files)
    rebuilt = patch_image.patched_files(_event(patch, root / sub), root)
    assert {str(Path(path).relative_to(root)): text for path, text in rebuilt.items()} == CODEX_WROTE[name]


def test_two_patches_in_one_command_are_both_read(tmp_path: Path) -> None:
    command = (
        f"apply_patch <<'EOF'\n{_patch('*** Add File: a.txt' + chr(10) + '+ok')}\nEOF\n"
        f"apply_patch <<'EOF'\n{_patch('*** Add File: b.txt' + chr(10) + '+' + TOKEN)}\nEOF\n"
    )
    assert patch_image.patched_files(_event(command), tmp_path) == {"a.txt": "ok\n", "b.txt": f"{TOKEN}\n"}


#: Texts Codex refuses to parse ("invalid hunk" / "invalid patch"): the gate refuses them too.
UNPARSED = [
    "*** Begin Patch with no end",
    "*** End of File\n*** End Patch\n*** Begin Patch",
    "*** Begin Patch\n*** Add File: a.txt\n+x",
    "*** Begin Patch\nstray\n*** Update File: a.txt\n-a\n+b\n*** End Patch",
    "*** Begin Patch\n*** Update File: a.txt\n*** End of File\n*** End Patch",
    f"*** Begin Patch\n*** Add File: a.txt\n+{TOKEN}\n@@\n*** End Patch",
    "*** Begin Patch\n*** Add File: a.txt\n+x\n*** End of File\n*** End Patch",
    "*** Begin Patch\n*** Update File: a.txt\n@@\n@@\n+x\n*** End Patch",
    "*** Begin Patch\n*** Update File: a.txt\n@@\n+x\n\tz\n*** End Patch",
    "*** Begin Patch\n*** Update File: a.txt\n@@\n+x\n*** End of File\nz\n*** End Patch",
    "*** Begin Patch\n*** Environment ID: a\n*** Environment ID: b\n*** End Patch",
]


@pytest.mark.parametrize("patch", UNPARSED)
def test_a_patch_codex_would_not_parse_is_refused(tmp_path: Path, patch: str) -> None:
    with pytest.raises(ValueError, match="does not parse"):
        patch_image.patched_files(_event(patch), tmp_path)
    gate = _gate(tmp_path, CONTENT)
    with pytest.raises(ValueError, match="does not parse"):  # the runtime's dispatch refuses any exception
        write_gate.evaluate_gate(["--gate", str(gate)], _event(patch))


@pytest.mark.parametrize(
    "patch",
    [
        "*** Begin Patch\n*** Environment ID: e\n*** Add File: a.txt\n+x\n*** End Patch",
        "*** Begin Patch\n*** Add File: a.txt\n+x\n   *** End Patch   \n",
        "*** Begin Patch\n*** Update File: a.txt\n@@\n a\n+x\n *** End Patch\n\n",
    ],
)
def test_markers_codex_accepts_still_read(tmp_path: Path, patch: str) -> None:
    root = _files(tmp_path, {"a.txt": "a\n"})
    assert patch_image.patched_files(_event(patch), root) == {"a.txt": "x\n" if "Add" in patch else "a\nx\n"}


def test_an_indented_marker_inside_an_update_is_a_context_line() -> None:
    patch = _patch("*** Update File: a.txt\n@@\n *** Add File: b.txt\n+x")
    [(op, path, _, [chunk])] = patch_image.parse_patch(patch)
    assert (op, path, chunk["old"], chunk["added"]) == ("update", "a.txt", ["*** Add File: b.txt"], ["x"])


def test_up_to_two_carriage_returns_end_a_line_as_codex_reads_it(tmp_path: Path) -> None:
    patch = _patch("*** Add File: a.txt\n+x\r\r\n+y\r\r\r\n+z\r")
    assert patch_image.patched_files(_event(patch), tmp_path) == {"a.txt": "x\ny\r\nz\n"}


def test_a_path_keeps_what_codex_keeps() -> None:
    """Rust's trim() leaves \\x1c in place, where str.strip() would remove it."""
    [(_, path, _, _)] = patch_image.parse_patch(_patch("*** Add File: a.txt\x1c\n+x"))
    assert path == "a.txt\x1c"
