"""The gate at the agent's write path: same kinds, same policy, different material.

pre_tool guards the write path and misses what it does not recognise -- a shell heredoc
carries no file argument. stop reads what the turn actually left behind, so the write path
stops mattering. Both answer to `tool_use`, which is the word policies already use.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from conftest import init_repo, write_gate

from chock.gate.runner import AGENT_EVENTS, WRITE_PATH_KINDS, WriteContext, run

# AWS's own published example key, the same fixture tests/test_gate_core.py uses. It is the
# string under test here, so the gate's documented per-line waiver applies rather than a
# change to the gate.
SECRET = 'KEY = "AKIAIOSFODNN7EXAMPLE"\n'  # pragma: allowlist secret
CLEAN = "KEY = os.environ['KEY']\n"

PARAMS = {
    "scan": "added_lines",
    "allowlist_pragma": r"#\s*pragma:\s*allowlist\s+secret",
    "content_pattern": r"(?i)(AKIA[0-9A-Z]{16})",
}


def _gate(tmp_path: Path, on=("commit", "tool_use"), kind="content_regex", paths=None) -> Path:
    spec = {
        "kind": kind,
        "on": list(on),
        "action": "block",
        "message": "secret",
        "params": PARAMS if kind == "content_regex" else {"refs": ["main"]},
    }
    if paths is not None:
        spec["paths"] = paths
    return write_gate(tmp_path, spec)


def _writes(**files):
    return dict(files)


# --- a write is judged before it lands ------------------------------------------------------------


def test_a_write_carrying_a_secret_is_refused(tmp_path: Path) -> None:
    init_repo(tmp_path)
    assert run(_gate(tmp_path), "pre-tool-use", None, tmp_path, writes={"app.py": SECRET}) == 1


def test_a_clean_write_passes(tmp_path: Path) -> None:
    init_repo(tmp_path)
    assert run(_gate(tmp_path), "pre-tool-use", None, tmp_path, writes={"app.py": CLEAN}) == 0


def test_the_same_judgement_is_made_at_the_turns_end(tmp_path: Path) -> None:
    """stop exists for the write pre_tool never saw; it must not judge differently."""
    init_repo(tmp_path)
    assert run(_gate(tmp_path), "stop", None, tmp_path, writes={"app.py": SECRET}) == 1
    assert run(_gate(tmp_path), "stop", None, tmp_path, writes={"app.py": CLEAN}) == 0


# --- the waiver is a second lever, and the agent must not be able to pull it ----------------------

WAIVED = 'KEY = "AKIAIOSFODNN7EXAMPLE"  # pragma: allowlist secret\n'


def test_the_line_pragma_is_not_honoured_at_the_write_path(tmp_path: Path) -> None:
    """The refused party could append the token to the very line it was refused on.

    The published policy message says the pragma is not honoured at tool-use, and the gateway
    evaluator never read it. This runner honoured it anyway, so the sentence became false the
    moment a write path was emitted through here. tests/test_gate_core.py pins that the same
    line IS waived at commit, where a human staged it.
    """
    init_repo(tmp_path)
    assert run(_gate(tmp_path), "pre-tool-use", None, tmp_path, writes={"app.py": WAIVED}) == 1


def test_the_line_pragma_is_not_honoured_at_the_turns_end_either(tmp_path: Path) -> None:
    """At stop the text is a file the agent just wrote; the same hand held both pens."""
    init_repo(tmp_path)
    assert run(_gate(tmp_path), "stop", None, tmp_path, writes={"app.py": WAIVED}) == 1


def test_a_forbidden_path_cannot_be_waived_from_inside_itself(tmp_path: Path) -> None:
    """The blob-level waiver for a forbidden path is the same lever, held the same way."""
    init_repo(tmp_path)
    spec = {
        "kind": "content_regex",
        "on": ["commit", "tool_use"],
        "action": "block",
        "message": "secret file",
        "params": {**PARAMS, "forbidden_path_regex": r"\.env$"},
    }
    gate = write_gate(tmp_path, spec)
    assert run(gate, "pre-tool-use", None, tmp_path, writes={".env": "# pragma: allowlist secret\nx=1\n"}) == 1


def test_the_waivable_events_are_exactly_the_staged_ones() -> None:
    """A new event defaults to unwaivable: an omission here fails closed, never open."""
    from chock.gate.runner import _EVENT_NAME, WAIVABLE_EVENTS

    agent_names = {_EVENT_NAME[event] for event in AGENT_EVENTS}
    assert not (agent_names & WAIVABLE_EVENTS), "an agent event has become waivable"
    assert WAIVABLE_EVENTS == {"commit", "push", "ci"}


def test_a_gate_that_does_not_declare_tool_use_stays_out_of_the_session(tmp_path: Path) -> None:
    init_repo(tmp_path)
    commit_only = _gate(tmp_path, on=("commit",))
    assert run(commit_only, "pre-tool-use", None, tmp_path, writes={"app.py": SECRET}) == 0


def test_applies_to_paths_bounds_the_write_path_too(tmp_path: Path) -> None:
    """Without this a pattern refuses the very file that documents it."""
    init_repo(tmp_path)
    scoped = _gate(tmp_path, paths=["src/*"])
    assert run(scoped, "pre-tool-use", None, tmp_path, writes={"src/app.py": SECRET}) == 1
    assert run(scoped, "pre-tool-use", None, tmp_path, writes={"docs/secrets.md": SECRET}) == 0


# --- what it refuses to answer --------------------------------------------------------------------


def test_a_kind_that_cannot_read_a_write_refuses_rather_than_allowing(tmp_path: Path) -> None:
    """A branch name is not in a tool call. Passing it empty would report an allow it never made."""
    init_repo(tmp_path)
    assert "forbidden_ref" not in WRITE_PATH_KINDS
    branch_gate = _gate(tmp_path, kind="forbidden_ref")
    assert run(branch_gate, "pre-tool-use", None, tmp_path, writes={"app.py": SECRET}) == 2


def test_no_writes_at_all_finds_nothing(tmp_path: Path) -> None:
    init_repo(tmp_path)
    assert run(_gate(tmp_path), "pre-tool-use", None, tmp_path, writes={}) == 0
    assert run(_gate(tmp_path), "pre-tool-use", None, tmp_path, writes=None) == 0


# --- the context itself ---------------------------------------------------------------------------


def test_every_line_of_a_write_is_an_added_line(tmp_path: Path) -> None:
    """A whole-file write adds all of it; an edit carries exactly the text being introduced."""
    ctx = WriteContext(repo_root=tmp_path, writes={"a.py": "one\ntwo\n"})
    assert ctx.added_lines("a.py") == ["one", "two"]
    assert ctx.staged_blob("a.py") == "one\ntwo\n"
    assert ctx.staged_paths() == ["a.py"]
    assert ctx.removed_lines("a.py") == [], "a write that has not landed removes nothing"


def test_the_context_still_knows_where_the_repository_is(tmp_path: Path) -> None:
    """An allowlist file lives in the repo even when the content under judgement does not."""
    (tmp_path / "on-disk.txt").write_text("before\n", encoding="utf-8")
    ctx = WriteContext(repo_root=tmp_path, writes={"on-disk.txt": "after\n"})
    assert ctx.repo_root == tmp_path
    assert ctx.head_blob("on-disk.txt") == "before\n", "what this write would replace"
    assert ctx.head_blob("never-existed.txt") == ""


# --- the wire the hook actually uses ----------------------------------------------------------------


def _cli(runner: Path, gate: Path, event: str, payload: dict, cwd: Path):
    return subprocess.run(
        [sys.executable, str(runner), "run", "--gate", str(gate), "--event", event],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        cwd=str(cwd),
        check=False,
    )


def test_the_runner_reads_the_writes_from_stdin(tmp_path: Path, gate_py: Path) -> None:
    init_repo(tmp_path)
    gate = _gate(tmp_path)
    assert _cli(gate_py, gate, "pre-tool-use", {"writes": {"app.py": SECRET}}, tmp_path).returncode == 1
    assert _cli(gate_py, gate, "pre-tool-use", {"writes": {"app.py": CLEAN}}, tmp_path).returncode == 0


def test_every_agent_event_is_reachable_from_the_command_line(tmp_path: Path, gate_py: Path) -> None:
    init_repo(tmp_path)
    gate = _gate(tmp_path)
    for event in AGENT_EVENTS:
        assert _cli(gate_py, gate, event, {"writes": {"app.py": SECRET}}, tmp_path).returncode == 1


def test_unreadable_stdin_judges_nothing_rather_than_guessing(tmp_path: Path, gate_py: Path) -> None:
    init_repo(tmp_path)
    result = _cli(gate_py, _gate(tmp_path), "pre-tool-use", {}, tmp_path)
    assert result.returncode == 0
