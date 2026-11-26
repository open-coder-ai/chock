"""The gate reads `git diff` structurally: a hunk line is classified by its first character, never by a prefix."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from conftest import init_repo, write_gate

from chock.gate.assemble import runner_source
from chock.gate.runner import GateContext, run
from chock.gate.runner.context import DiffError, ListingError, _diff_sides

TOKEN = "FORBIDDEN_TOKEN"
#: Added content a header filter mistook for a `+++` file header, or that `str.splitlines` cut off its `+`.
ADDED = {
    "double_plus": f"++{TOKEN}\n",
    "header_lookalike": f"+++ b/x {TOKEN}\n",
    "file_separator": f"ok\x1c{TOKEN}\n",
    "line_separator": f"ok\u2028{TOKEN}\n",
    "no_final_newline": f"ok\n{TOKEN}",
}


def _repo(tmp_path: Path) -> Path:
    (tmp_path / "repo").mkdir()
    return init_repo(tmp_path / "repo")


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def _stage(repo: Path, name: str, content: str | bytes) -> None:
    path = repo / name
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, encoding="utf-8", newline="")
    _git(repo, "add", "--", name)


def _content_gate(repo: Path) -> Path:
    params = {"scan": "added_lines", "content_pattern": TOKEN}
    return write_gate(
        repo.parent, {"kind": "content_regex", "on": ["commit"], "action": "block", "message": "m", "params": params}
    )


def _integrity_gate(repo: Path) -> Path:
    params = {"test_path_regex": r"^test_", "assertion_pattern": r"check\("}
    return write_gate(
        repo.parent, {"kind": "test_integrity", "on": ["commit"], "action": "block", "message": "m", "params": params}
    )


@pytest.mark.parametrize("label", ADDED)
def test_added_content_is_blocked_whatever_it_starts_with(tmp_path: Path, label: str) -> None:
    repo = _repo(tmp_path)
    _stage(repo, "a.txt", ADDED[label])
    assert run(_content_gate(repo), "pre-commit", None, repo) == 1


def test_a_header_lookalike_is_blocked_in_range_mode(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _stage(repo, "a.txt", "seed\n")
    _git(repo, "commit", "-q", "-m", "base")
    _git(repo, "branch", "trunk")
    _stage(repo, "a.txt", f"seed\n+++ b/x {TOKEN}\n")
    _git(repo, "commit", "-q", "-m", "change")
    assert run(_content_gate(repo), "ci", None, repo, base="trunk") == 1


def test_removed_lines_starting_with_dashes_are_counted(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _stage(repo, "test_a.lua", "x()\n--check(a)\n--check(b)\n")
    _git(repo, "commit", "-q", "-m", "base")
    _stage(repo, "test_a.lua", "x()\n")
    assert run(_integrity_gate(repo), "pre-commit", None, repo) == 1


def test_added_content_survives_a_rename(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _stage(repo, "old.txt", "one\ntwo\nthree\nfour\n")
    _git(repo, "commit", "-q", "-m", "base")
    _git(repo, "mv", "old.txt", "new.txt")
    _stage(repo, "new.txt", f"one\ntwo\nthree\nfour\n++{TOKEN}\n")
    assert run(_content_gate(repo), "pre-commit", None, repo) == 1


def test_clean_content_is_allowed(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _stage(repo, "a.txt", "++fine\n+++ b/x\n--- a/x\n")
    assert run(_content_gate(repo), "pre-commit", None, repo) == 0


def test_a_binary_file_has_no_added_lines(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _stage(repo, "a.bin", b"\0" + TOKEN.encode())
    assert GateContext(repo_root=repo).added_lines("a.bin") == []


def test_a_diff_git_cannot_produce_refuses(tmp_path: Path) -> None:
    (tmp_path / "plain").mkdir()
    with pytest.raises(DiffError):
        GateContext(repo_root=tmp_path / "plain").added_lines("a.txt")


def test_an_unreadable_diff_refuses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    repo = _repo(tmp_path)
    _stage(repo, "a.txt", "fine\n")
    monkeypatch.setattr(GateContext, "_diff_text", lambda *_: "@@ -0,0 +1 @@\n+fine\n")
    assert run(_content_gate(repo), "pre-commit", None, repo) == 2
    assert "refusing" in capsys.readouterr().err


HEADER = "diff --git a/x b/x\nindex 1..2 100644\n--- a/x\n+++ b/x\n"


def test_hunk_lines_are_classified_by_their_first_character() -> None:
    text = HEADER + "@@ -1,2 +1,3 @@\n--- a/x\n-old\n++++ b/x\n+++x\n\\ No newline at end of file\n+new\n"
    assert _diff_sides(text) == (["+++ b/x", "++x", "new"], ["-- a/x", "old"])


def test_counts_default_to_one_and_several_files_parse() -> None:
    text = HEADER + "@@ -1 +1 @@\n-a\n+b\n" + HEADER + "@@ -0,0 +1,2 @@\n+c\n+d\n"
    assert _diff_sides(text) == (["b", "c", "d"], ["a"])


def test_headers_without_hunks_parse() -> None:
    binary = "diff --git a/x b/x\nnew file mode 100644\nindex 0..1\nBinary files /dev/null and b/x differ\n"
    rename = "diff --git a/x b/y\nsimilarity index 100%\nrename from x\nrename to y\n"
    mode = "diff --git a/x b/x\nold mode 100644\nnew mode 100755\n"
    assert _diff_sides("") == ([], [])
    assert _diff_sides(binary + rename + mode) == ([], [])


@pytest.mark.parametrize(
    "text",
    [
        "@@ -1 +1 @@\n+a\n",  # a hunk before any file header
        HEADER + "+a\n",  # an added line outside a hunk
        HEADER + "@@ -1,2 +1 @@\n-a\n+b\n",  # a hunk that ends early
        HEADER + "@@ -1 +1 @@\n-a\n+b\n+c\n",  # a line past the hunk's counts
        HEADER + "@@ -1 +1 @@\n-a\n?b\n",  # a line with no known first character
        HEADER + "@@ -1 +x @@\n",  # a malformed hunk header
        "diff --git a/x b/x\nweird header\n",  # a header line git does not write
    ],
)
def test_a_diff_that_does_not_parse_raises(text: str) -> None:
    with pytest.raises(DiffError):
        _diff_sides(text)


def test_a_diff_error_is_a_refusal() -> None:
    assert issubclass(DiffError, ListingError)


def test_the_vendored_gate_blocks_a_header_lookalike(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _stage(repo, "a.txt", f"+++ b/x {TOKEN}\n")
    runtime = tmp_path / "gate.py"
    runtime.write_text(runner_source(), encoding="utf-8")
    argv = [sys.executable, str(runtime), "run", "--gate", str(_content_gate(repo)), "--event", "pre-commit"]
    proc = subprocess.run(argv, cwd=repo, capture_output=True, text=True, check=False)
    assert proc.returncode == 1, proc.stderr
