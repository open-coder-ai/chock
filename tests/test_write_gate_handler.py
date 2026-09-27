"""The handler half of the write path: what it hands the runner, and what it refuses to decide.

Nothing here judges content. It finds the gate, gathers the material, asks the runner, and
translates the answer -- so a policy cannot mean one thing at commit and another in session.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

from conftest import init_repo

from chock.gate import write_gate

SECRET = 'KEY = "AKIAIOSFODNN7EXAMPLE"\n'  # pragma: allowlist secret -- the string under test

SPEC = {
    "kind": "content_regex",
    "on": ["commit", "tool_use"],
    "action": "block",
    "message": "secret",
    "params": {"scan": "added_lines", "content_pattern": r"(?i)(AKIA[0-9A-Z]{16})"},
}


def _event(name="pre_tool", path=None, content=None, raw=None):
    return SimpleNamespace(event=name, path=path, content=content, raw=raw or {})


def _installed(tmp_path: Path) -> Path:
    """A repo laid out the way `chock sync` leaves one: a compiled gate and a vendored runner."""
    gate = tmp_path / ".chock" / "compiled" / "scan-secrets" / "pre-tool-use" / "gate.json"
    gate.parent.mkdir(parents=True)
    gate.write_text(json.dumps(SPEC), encoding="utf-8")
    runner = tmp_path / ".chock" / "bin" / "gate.py"
    runner.parent.mkdir(parents=True)
    source = Path(__file__).resolve().parents[1] / "src" / "chock" / "gate" / "runner.py"
    runner.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    return gate


# --- finding its own parts ------------------------------------------------------------------------


def test_it_derives_the_runner_and_root_from_the_gates_own_place(tmp_path: Path) -> None:
    """Derived, not searched upwards: a walk could find a nested checkout's .chock instead."""
    gate = _installed(tmp_path)
    assert write_gate.runner_for(gate) == tmp_path / ".chock" / "bin" / "gate.py"
    assert write_gate.root_for(gate) == tmp_path


def test_a_gate_somewhere_else_yields_no_runner(tmp_path: Path) -> None:
    stray = tmp_path / "gate.json"
    stray.write_text("{}", encoding="utf-8")
    assert write_gate.runner_for(stray) is None


def test_the_flag_is_read_off_the_command_line(tmp_path: Path) -> None:
    assert write_gate.gate_path_from_argv(["--gate", "/x/gate.json"]) == Path("/x/gate.json")
    assert write_gate.gate_path_from_argv(["--guard", "/x/g.sh"]) is None
    assert write_gate.gate_path_from_argv(["--gate"]) is None, "a flag with no value names nothing"


# --- what each event puts under judgement ----------------------------------------------------------


def test_a_write_call_offers_its_own_text(tmp_path: Path) -> None:
    gate = _installed(tmp_path)
    event = _event(path="app.py", content=SECRET)
    assert write_gate.writes_for(event, gate) == {"app.py": SECRET}


def test_a_call_carrying_no_file_text_offers_nothing(tmp_path: Path) -> None:
    gate = _installed(tmp_path)
    assert write_gate.writes_for(_event(path="app.py", content=None), gate) == {}
    assert write_gate.writes_for(_event(path=None, content=SECRET), gate) == {}


def test_the_turns_end_reads_what_is_on_disk_however_it_got_there(tmp_path: Path) -> None:
    """The write path misses a shell heredoc; reading final state is what closes that."""
    gate = _installed(tmp_path)
    init_repo(tmp_path)
    (tmp_path / "written_by_bash.py").write_text(SECRET, encoding="utf-8")
    writes = write_gate.writes_for(_event("stop"), gate)
    assert writes.get("written_by_bash.py") == SECRET


def test_a_stop_hook_already_active_reads_nothing(tmp_path: Path) -> None:
    """A refusal that re-entered its own stop hook would never terminate."""
    gate = _installed(tmp_path)
    init_repo(tmp_path)
    (tmp_path / "app.py").write_text(SECRET, encoding="utf-8")
    assert write_gate.writes_for(_event("stop", raw={"stop_hook_active": True}), gate) == {}


def test_a_deletion_leaves_no_content_to_judge(tmp_path: Path) -> None:
    init_repo(tmp_path)
    (tmp_path / "gone.py").write_text("x = 1\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "add", "-A"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-m", "add"], check=True, capture_output=True)
    (tmp_path / "gone.py").unlink()
    assert "gone.py" not in write_gate.writes_from_worktree(tmp_path)


# --- the decision it returns -------------------------------------------------------------------------


def test_a_refused_write_becomes_a_denial(tmp_path: Path) -> None:
    gate = _installed(tmp_path)
    verdict = write_gate.evaluate_gate(["--gate", str(gate)], _event(path="app.py", content=SECRET))
    assert verdict is not None
    assert verdict[0] == write_gate.VERDICT_DENY


def test_a_clean_write_earns_no_decision_at_all(tmp_path: Path) -> None:
    gate = _installed(tmp_path)
    clean = _event(path="app.py", content="KEY = os.environ['KEY']\n")
    assert write_gate.evaluate_gate(["--gate", str(gate)], clean) is None


def test_no_gate_flag_means_this_handler_has_nothing_to_say(tmp_path: Path) -> None:
    """Until an emitter passes --gate, the whole path is inert -- nothing installed changes."""
    assert write_gate.evaluate_gate(["--guard", "/x/g.sh"], _event(path="a.py", content=SECRET)) is None


def test_an_event_this_handler_does_not_gate_is_left_alone(tmp_path: Path) -> None:
    gate = _installed(tmp_path)
    assert write_gate.evaluate_gate(["--gate", str(gate)], _event("session_start")) is None


def test_a_runner_that_cannot_answer_refuses_rather_than_allowing(tmp_path: Path) -> None:
    """An unreadable check is not an allow; saying so is the whole posture of this pack."""
    gate = _installed(tmp_path)
    (tmp_path / ".chock" / "bin" / "gate.py").write_text("raise SystemExit(9)\n", encoding="utf-8")
    verdict = write_gate.evaluate_gate(["--gate", str(gate)], _event(path="app.py", content=SECRET))
    assert verdict is not None
    assert verdict[0] == write_gate.VERDICT_DENY
    assert "could not check" in verdict[1]


def test_a_missing_runner_refuses_too(tmp_path: Path) -> None:
    gate = _installed(tmp_path)
    (tmp_path / ".chock" / "bin" / "gate.py").unlink()
    verdict = write_gate.evaluate_gate(["--gate", str(gate)], _event(path="app.py", content=SECRET))
    assert verdict is not None and verdict[0] == write_gate.VERDICT_DENY


# --- a client names the file absolutely; a scope glob is repository-relative ----------------------

UNPINNED = "      - uses: actions/checkout@v4\n"
PIN_SPEC = {
    "kind": "content_regex",
    "on": ["commit", "tool_use"],
    "action": "block",
    "message": "pin it",
    "paths": [".github/workflows/*"],
    "params": {"scan": "added_lines", "content_pattern": r"uses:\s*[\w./-]+@(?![0-9a-fA-F]{40})[\w./-]+"},
}


def _installed_pin(tmp_path: Path) -> Path:
    gate = _installed(tmp_path)
    gate.write_text(json.dumps(PIN_SPEC), encoding="utf-8")
    return gate


def test_a_scoped_gate_judges_a_write_named_by_its_absolute_path(tmp_path: Path) -> None:
    """Claude Code and Cursor send tool_input.file_path absolute; the scope must still match it."""
    gate = _installed_pin(tmp_path)
    absolute = tmp_path / ".github" / "workflows" / "ci.yml"
    verdict = write_gate.evaluate_gate(["--gate", str(gate)], _event(path=str(absolute), content=UNPINNED))
    assert verdict is not None and verdict[0] == write_gate.VERDICT_DENY


def test_an_absolute_path_reached_through_a_symlink_is_still_inside(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    gate = _installed_pin(real)
    (tmp_path / "link").symlink_to(real, target_is_directory=True)
    via_link = tmp_path / "link" / ".github" / "workflows" / "ci.yml"
    verdict = write_gate.evaluate_gate(["--gate", str(gate)], _event(path=str(via_link), content=UNPINNED))
    assert verdict is not None and verdict[0] == write_gate.VERDICT_DENY


def test_paths_are_made_repository_relative_posix() -> None:
    assert write_gate.repo_relative("/r/.github/workflows/ci.yml", "/r") == ".github/workflows/ci.yml"
    assert write_gate.repo_relative("./a/../.github/x.yml", "/r") == ".github/x.yml"
    assert write_gate.repo_relative(".github/x.yml", None) == ".github/x.yml"


def test_windows_paths_fold_drive_separator_and_case() -> None:
    windows = r"C:\Users\Dev\Repo\.github\workflows\ci.yml"
    assert write_gate.repo_relative(windows, r"c:\users\dev\repo") == ".github/workflows/ci.yml"
    assert write_gate.repo_relative("C:/Users/Dev/Repo/.github/x.yml", r"C:\Users\Dev\Repo") == ".github/x.yml"


def test_a_path_outside_the_repository_is_left_as_given() -> None:
    """Outside the root it matches no relative glob, which is what out of scope means."""
    assert (
        write_gate.repo_relative("/elsewhere/.github/workflows/ci.yml", "/r") == "/elsewhere/.github/workflows/ci.yml"
    )
    assert write_gate.repo_relative(r"D:\x\ci.yml", r"C:\Repo") == r"D:\x\ci.yml"
