"""`outside_repo`: a gate sees a write outside the repository only when its own globs declare the path."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tool_call_support import POLICY_ID, fire, make_repo

from chock.gate.outside_repo import declared_outside, expand_home, is_outside, judged_files
from chock.hooks.in_agent_install import install_hooks
from chock.validation.checks_gate_shape import _validate_gate
from chock.validation.report import Report

GATE = ".chock/compiled/guard-tools/pre-tool-use/gate.json"
LEAK = "AKIA" + "1234567890ABCDEF"  # pragma: allowlist secret -- the string under test
ROOT = "/repo"


def _gate(**extra) -> dict:
    return {
        "kind": "content_regex",
        "on": ["commit", "tool_use"],
        "params": {"content_pattern": "AKIA[0-9A-Z]{16}"},
        "outside_repo": ["~/.claude/memory/*"],
        **extra,
    }


def _write(repo: Path, target: Path | str):
    payload = {
        "hook_event_name": "PreToolUse",
        "tool_name": "Write",
        "tool_input": {"file_path": str(target), "content": f'key = "{LEAK}"\n'},
        "session_id": "s",
        "cwd": str(repo),
    }
    return fire(repo, ["--gate", GATE], payload)


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "users" / "dev"
    (home / ".claude" / "memory").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    return home


def _blocked(proc) -> bool:
    return proc.returncode == 2 or '"deny"' in proc.stdout


def test_a_declared_outside_path_is_judged(tmp_path: Path, home: Path) -> None:
    repo = make_repo(tmp_path, _gate())
    install_hooks(repo, "claude_code")
    assert _blocked(_write(repo, home / ".claude" / "memory" / "MEMORY.md"))


def test_an_undeclared_outside_path_is_ignored(tmp_path: Path, home: Path) -> None:
    repo = make_repo(tmp_path, _gate())
    install_hooks(repo, "claude_code")
    assert not _blocked(_write(repo, home / "notes.txt"))
    assert not _blocked(_write(repo, home / ".claude" / "settings.json"))


def test_without_the_declaration_no_outside_write_is_judged(tmp_path: Path, home: Path) -> None:
    gate = _gate()
    del gate["outside_repo"]
    repo = make_repo(tmp_path, gate)
    install_hooks(repo, "claude_code")
    assert not _blocked(_write(repo, home / ".claude" / "memory" / "MEMORY.md"))


def test_a_write_inside_the_repository_is_still_judged(tmp_path: Path, home: Path) -> None:
    repo = make_repo(tmp_path, _gate())
    install_hooks(repo, "claude_code")
    assert _blocked(_write(repo, repo / "src" / "app.py"))


def test_applies_to_paths_bounds_the_repo_and_not_the_declared_outside_path(tmp_path: Path, home: Path) -> None:
    repo = make_repo(tmp_path, _gate(), applies_to={"paths": ["docs/*"]})
    install_hooks(repo, "claude_code")
    assert not _blocked(_write(repo, repo / "src" / "app.py"))
    assert _blocked(_write(repo, home / ".claude" / "memory" / "MEMORY.md"))


def test_a_script_gate_receives_the_absolute_path_as_the_writes_key(tmp_path: Path, home: Path) -> None:
    script = (
        "import json, sys\npayload = json.load(sys.stdin)\n"
        "open(payload['repo_root'] + '/writes.json', 'w').write(json.dumps(sorted(payload['writes'])))\n"
    )
    gate = _gate()
    gate["kind"], gate["params"] = "script", {"script": "judge.py"}
    repo = make_repo(tmp_path, gate, script=script)
    install_hooks(repo, "claude_code")
    target = home / ".claude" / "memory" / "MEMORY.md"
    _write(repo, target)
    assert json.loads((repo / "writes.json").read_text()) == [target.as_posix()]


def test_an_outside_path_climbing_out_of_the_repo_is_matched_by_where_it_lands(tmp_path: Path, home: Path) -> None:
    repo = make_repo(tmp_path, _gate())
    install_hooks(repo, "claude_code")
    climb = Path("..") / "users" / "dev" / ".claude" / "memory" / "MEMORY.md"
    assert _blocked(_write(repo, climb))


# --- the matcher, without a process --------------------------------------------------------------


def test_tilde_expands_per_machine_alone_or_before_a_separator(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", "/users/dev")
    assert expand_home("~/.claude/x") == "/users/dev/.claude/x"
    assert expand_home("~\\.claude\\x") == "/users/dev\\.claude\\x"
    assert expand_home("~") == "/users/dev"
    assert expand_home("~other/x") == "~other/x"


@pytest.mark.parametrize(
    ("path", "outside"),
    [("src/a.py", False), ("/etc/hosts", True), ("C:\\Users\\dev\\a.txt", True), ("../x", True), ("..hidden", False)],
)
def test_what_counts_as_outside(path: str, outside: bool) -> None:
    assert is_outside(path) is outside


def test_windows_spellings_and_case_compare_the_way_windows_does() -> None:
    globs = ["C:\\Users\\Dev\\.claude\\memory\\*"]
    hit = declared_outside("c:/users/dev/.claude/memory/MEMORY.md", ROOT, globs, windows=True)
    assert hit == "c:/users/dev/.claude/memory/MEMORY.md"
    assert declared_outside("C:\\Users\\Dev\\.claude\\memory\\a.md", ROOT, globs, windows=True) is not None
    assert declared_outside("C:\\Users\\Dev\\other.md", ROOT, globs, windows=True) is None
    assert (
        declared_outside("/users/dev/.claude/memory/a.md", ROOT, ["/Users/dev/.claude/memory/*"], windows=False) is None
    )


def test_judged_files_keeps_inside_names_and_only_declared_outside_ones() -> None:
    files = {"a.py": "1", "/users/dev/.claude/memory/M.md": "2", "/users/dev/other": "3"}
    kept = judged_files(files, ROOT, ["/users/dev/.claude/memory/*"], lambda path: (path,))
    assert kept == {"a.py": "1", "/users/dev/.claude/memory/M.md": "2"}


# --- validation ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("gate", "message"),
    [
        ({"on": ["commit"], "outside_repo": ["~/x"]}, "must include tool_use"),
        ({"on": ["commit", "tool_use"], "outside_repo": ["relative/*"]}, "absolute or start with ~"),
    ],
)
def test_validation_refuses_a_misdeclared_outside_repo(gate: dict, message: str) -> None:
    report = Report()
    _validate_gate(
        {"kind": "content_regex", "action": "block", "message": "m", "params": {"content_pattern": "x"}, **gate},
        POLICY_ID,
        report,
        tool_use_allowed=True,
    )
    assert any(message in f.message for f in report.errors), [f.message for f in report.errors]
