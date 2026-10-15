"""STOP-EVERYWHERE: `chock stop --everywhere` refuses every agent on the machine; `chock resume --everywhere` lifts it."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from types import SimpleNamespace

import pytest
from conftest import init_repo
from decision_log_support import CLEAN_GUARD, plugin_layout, records, sync_layout, sync_log
from stop_person_support import person_resume, person_resume_everywhere
from test_repo_stop_gap1c import _call, _deny, _hook
from test_repo_stop_git import AGENT, PERSON, _commit
from test_repo_stop_git import repo as git_repo  # noqa: F401 -- the fixture, under the name the tests use

from chock import stop as chock_stop
from chock.doctor.cli import main as doctor_main
from chock.gate.repo_stop import repo_stop_refusal
from chock.gate.runner.halt import (
    HALT_EVERYWHERE_NAME,
    halt_everywhere_entry,
    halt_registry_dir,
    halt_registry_entry,
)
from chock.gateway.stop import stop_refusal
from chock.lifecycle import status_main

pytestmark = pytest.mark.usefixtures("private_home")

REASON = "machine incident"
MACHINE = "every agent on this machine"


def _stop_everywhere(*args: str) -> int:
    return chock_stop.stop_main(["--everywhere", "--reason", REASON, *args])


def _event(cwd: Path, agent: str | None = "claude_code") -> SimpleNamespace:
    return SimpleNamespace(event="pre_tool", agent=agent, cwd=str(cwd), raw={}, path=None)


def _repo(path: Path) -> Path:
    path.mkdir(parents=True)
    return init_repo(path)


def test_the_entry_is_private_in_the_registry_and_cannot_be_a_repos_entry(tmp_path: Path) -> None:
    assert _stop_everywhere("--repo", str(tmp_path)) == 0
    entry = halt_everywhere_entry()
    assert entry.parent == halt_registry_dir()
    assert entry.name == HALT_EVERYWHERE_NAME
    assert halt_registry_entry(tmp_path).name != entry.name
    assert not set(entry.stem) <= set("0123456789abcdef")
    doc = json.loads(entry.read_text(encoding="utf-8"))
    assert (doc["scope"], doc["reason"], doc["everywhere"]) == ("all", REASON, True)
    if os.name == "posix":
        assert stat.S_IMODE(entry.stat().st_mode) == 0o600
        assert stat.S_IMODE(entry.parent.stat().st_mode) == 0o700


def test_it_takes_no_agent(tmp_path: Path) -> None:
    assert _stop_everywhere("--repo", str(tmp_path), "--agent", "cursor") == 2
    assert not os.path.lexists(halt_everywhere_entry())


@pytest.mark.parametrize("agent", ["claude_code", "cursor", None, "someone_new"])
def test_every_agent_in_every_repo_and_session_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, agent: str | None
) -> None:
    other = _repo(tmp_path / "b")
    outside = tmp_path / "out"
    outside.mkdir()
    assert repo_stop_refusal(_event(other, agent)) is None
    assert _stop_everywhere("--repo", str(outside)) == 0
    assert MACHINE in repo_stop_refusal(_event(outside, agent))
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(other))  # a session the client places in an unstopped repo
    refused = repo_stop_refusal(_event(other, agent))
    assert f"stopped: {REASON}" in refused
    assert "`chock resume --everywhere`" in refused


def test_the_gateway_refuses(tmp_path: Path) -> None:
    other = _repo(tmp_path / "b")
    assert stop_refusal(other, [], "claude_code") is None
    assert _stop_everywhere("--repo", str(other)) == 0
    assert MACHINE in stop_refusal(other, [str(other)], "claude_code")


@pytest.mark.parametrize("route", ["sync", "plugin"])
def test_the_runtime_refuses_a_read_on_either_route(tmp_path: Path, private_home: Path, route: str) -> None:
    repo, runtime, _ = (sync_layout if route == "sync" else plugin_layout)(tmp_path, CLEAN_GUARD)
    read = _call("Read", {"file_path": str(repo / "notes.txt")}, repo)
    assert not _deny(_hook(runtime, repo, read, private_home, CLAUDE_PROJECT_DIR=str(repo)))
    assert _stop_everywhere("--repo", str(tmp_path)) == 0
    refused = _hook(runtime, repo, read, private_home, CLAUDE_PROJECT_DIR=str(repo))
    assert _deny(refused), refused.stdout
    assert MACHINE in refused.stdout


def _damage(entry: Path, how: str) -> None:
    entry.parent.mkdir(parents=True, exist_ok=True)
    if how == "corrupt":
        entry.write_text("{", encoding="utf-8")
    elif how == "folder":
        entry.mkdir()
    elif how == "symlink":
        target = entry.parent.parent / "elsewhere.json"
        target.write_text(json.dumps({"scope": "all", "reason": "via a link"}), encoding="utf-8")
        entry.symlink_to(target)
    elif how == "dangling":
        entry.symlink_to(entry.parent / "gone.json")
    elif how == "binary":
        entry.write_bytes(b"\xff\xfe\x00")


@pytest.mark.parametrize("how", ["corrupt", "folder", "symlink", "dangling", "binary"])
def test_a_damaged_or_irregular_entry_refuses(tmp_path: Path, how: str) -> None:
    if how in ("symlink", "dangling") and os.name != "posix":
        pytest.skip("symlinks need privileges on Windows")
    _damage(halt_everywhere_entry(), how)
    refused = repo_stop_refusal(_event(tmp_path))
    assert refused is not None
    assert MACHINE in refused


def test_a_scope_naming_one_agent_still_reaches_every_agent(tmp_path: Path) -> None:
    entry = halt_everywhere_entry()
    entry.parent.mkdir(parents=True)
    entry.write_text(json.dumps({"scope": "cursor", "reason": REASON}), encoding="utf-8")
    assert f"stopped: {REASON}" in repo_stop_refusal(_event(tmp_path, "claude_code"))


@pytest.mark.skipif(os.name != "posix" or os.geteuid() == 0, reason="root reads a mode-000 file")
def test_an_unreadable_entry_refuses(tmp_path: Path) -> None:
    entry = halt_everywhere_entry()
    entry.parent.mkdir(parents=True)
    entry.write_text("{}", encoding="utf-8")
    entry.chmod(0)
    assert "cannot be read" in repo_stop_refusal(_event(tmp_path))


def test_an_agents_commit_is_refused_and_a_persons_passes(git_repo: Path) -> None:  # noqa: F811
    assert _stop_everywhere("--repo", str(git_repo.parent)) == 0
    refused = _commit(git_repo, AGENT)
    assert refused.returncode != 0
    assert MACHINE in refused.stderr
    assert "`chock resume --everywhere`" in refused.stderr
    assert _commit(git_repo, PERSON).returncode == 0


def test_without_gate_py_the_machine_stop_refuses_no_commit_blind(git_repo: Path) -> None:  # noqa: F811
    """Only gate.py tells an agent from a person; without it the machine stop is the pre-tool hook's, never the git hook's."""
    (git_repo / ".chock" / "bin" / "gate.py").unlink()
    assert _stop_everywhere("--repo", str(git_repo.parent)) == 0
    passed = _commit(git_repo, PERSON)
    assert passed.returncode == 0, passed.stderr
    assert chock_stop.stop_main(["--repo", str(git_repo)]) == 0
    refused = _commit(git_repo, PERSON)
    assert refused.returncode != 0
    assert ".chock/stop.json is in force" in refused.stderr


def test_an_agents_stop_and_resume_are_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CHOCK_GATE_LOG")
    repo = _repo(tmp_path / "a")
    monkeypatch.setenv("CLAUDECODE", "1")
    assert _stop_everywhere("--repo", str(repo)) == 1
    assert not os.path.lexists(halt_everywhere_entry())
    monkeypatch.delenv("CLAUDECODE")
    assert _stop_everywhere("--repo", str(repo)) == 0
    monkeypatch.setenv("AI_AGENT", "claude-code_2_agent")
    assert person_resume_everywhere(repo=repo) == 1
    assert halt_everywhere_entry().is_file()
    refusals = [r for r in records(sync_log(repo)) if r.get("verdict") == "block"]
    assert [(r["event"], r["everywhere"]) for r in refusals] == [("repo_stop", True), ("repo_resume", True)]


def test_resume_needs_a_terminal_and_the_typed_word(tmp_path: Path) -> None:
    assert _stop_everywhere("--repo", str(tmp_path)) == 0
    assert chock_stop.resume_main(["--repo", str(tmp_path), "--everywhere"]) == 1  # pytest's stdin is no TTY
    assert person_resume_everywhere("yes", repo=tmp_path) == 1
    assert person_resume_everywhere(tmp_path.name, repo=tmp_path) == 1
    assert halt_everywhere_entry().is_file()
    assert person_resume_everywhere(repo=tmp_path) == 0
    assert not os.path.lexists(halt_everywhere_entry())
    assert repo_stop_refusal(_event(tmp_path)) is None


def test_resume_removes_a_damaged_entry(tmp_path: Path) -> None:
    _damage(halt_everywhere_entry(), "corrupt")
    assert person_resume_everywhere(repo=tmp_path) == 0
    assert repo_stop_refusal(_event(tmp_path)) is None


def test_resume_everywhere_lifts_no_repo_stop_and_says_so(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = _repo(tmp_path / "a")
    assert chock_stop.stop_main(["--repo", str(repo), "--reason", "one repo"]) == 0
    assert _stop_everywhere("--repo", str(repo)) == 0
    capsys.readouterr()
    assert person_resume_everywhere(repo=repo) == 0
    assert "`chock resume` there lifts it" in capsys.readouterr().out
    assert "stopped: one repo" in repo_stop_refusal(_event(repo))
    assert person_resume(repo) == 0
    assert repo_stop_refusal(_event(repo)) is None


def test_a_repo_resume_does_not_lift_the_machine_stop(tmp_path: Path) -> None:
    repo = _repo(tmp_path / "a")
    assert chock_stop.stop_main(["--repo", str(repo)]) == 0
    assert _stop_everywhere("--repo", str(repo)) == 0
    assert person_resume(repo) == 0
    assert MACHINE in repo_stop_refusal(_event(repo))


def test_inside_a_repo_the_stop_and_resume_are_logged_as_machine_wide(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("CHOCK_GATE_LOG")
    repo = _repo(tmp_path / "a")
    (repo / "sub").mkdir()
    assert _stop_everywhere("--repo", str(repo / "sub")) == 0
    assert person_resume_everywhere(repo=repo / "sub") == 0
    lines = [r for r in records(sync_log(repo)) if r["event"] in ("repo_stop", "repo_resume")]
    assert [(r["event"], r["everywhere"], r["actor"]) for r in lines] == [
        ("repo_stop", True, "person"),
        ("repo_resume", True, "person"),
    ]
    assert lines[0]["reason"] == REASON


def test_outside_every_repo_nothing_is_logged(tmp_path: Path) -> None:
    outside = tmp_path / "out"
    outside.mkdir()
    assert _stop_everywhere("--repo", str(outside)) == 0
    assert person_resume_everywhere(repo=outside) == 0
    assert not (outside / ".chock").exists()


def test_status_and_doctor_lead_with_the_machine_stop(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = _repo(tmp_path / "a")
    assert _stop_everywhere("--repo", str(repo)) == 0
    capsys.readouterr()
    status_main(["--repo", str(repo)])
    first = capsys.readouterr().out.splitlines()[0]
    assert first.startswith("STOPPED EVERYWHERE: every agent on this machine, by ")
    assert REASON in first
    doctor_main(["--repo", str(repo)])
    assert capsys.readouterr().out.startswith("STOPPED EVERYWHERE: ")
    halt_everywhere_entry().write_text("{", encoding="utf-8")
    status_main(["--repo", str(repo)])
    assert "cannot be read" in capsys.readouterr().out.splitlines()[0]


def test_nothing_stopped_shows_nothing(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = _repo(tmp_path / "a")
    status_main(["--repo", str(repo)])
    assert "STOPPED" not in capsys.readouterr().out
