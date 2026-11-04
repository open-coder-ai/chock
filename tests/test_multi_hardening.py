"""Multi-policy dispatch refuses on any fault, isolates each member's event, and confines member paths to the root."""

from __future__ import annotations

import hashlib
import json
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
from runtime_support import load_runtime

from chock.gate import multi

GUARD = "import sys\nsys.exit(0)\n"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _repo(tmp_path: Path, names=("alpha", "bravo")) -> tuple[Path, list[str]]:
    repo = tmp_path / "repo"
    (repo / "guards").mkdir(parents=True)
    members = []
    for name in names:
        guard = repo / "guards" / f"{name}.py"
        guard.write_text(GUARD, encoding="utf-8")
        members.append(
            {"argv": ["--guard", f"guards/{name}.py"], "timeout": 30, "files": {f"guards/{name}.py": _sha(guard)}}
        )
    index = repo / "index.json"
    index.write_text(json.dumps({"members": members}), encoding="utf-8")
    return repo, ["x.py", "--multi", "index.json", "--index-sha256", _sha(index)]


def _event(**overrides) -> SimpleNamespace:
    base = {"event": "pre_tool", "command": "ls", "tool": "Bash", "raw": {"k": ["v"]}, "path": None, "content": None}
    return SimpleNamespace(**{**base, **overrides})


@pytest.fixture
def _multi(tmp_path, monkeypatch):
    repo, argv = _repo(tmp_path)
    monkeypatch.chdir(repo)
    monkeypatch.setattr(sys, "argv", argv)
    ns = load_runtime(tmp_path / "runtime", "claude_code")
    ns["evaluate"] = lambda *_a, **_k: None
    ns["evaluate_gate"] = lambda *_a, **_k: None
    ns["evaluate_tool_call"] = lambda *_a, **_k: None
    return ns


def _assert_refused(ns, decision, text) -> None:
    assert decision is not None and decision.outcome == ns["DENY"], decision
    assert text in decision.reason
    assert "never established" in decision.reason


def test_the_clean_multi_call_still_allows(_multi) -> None:
    assert _multi["handle"](_event()) is None


def test_a_raise_in_combine_refuses(_multi) -> None:
    def blow_up(_verdicts):
        raise RuntimeError("combine broke")

    _multi["combine"] = blow_up
    _assert_refused(_multi, _multi["handle"](_event()), "RuntimeError: combine broke")


def test_a_failed_log_write_refuses(_multi) -> None:
    def blow_up(*_args, **_kwargs):
        raise OSError("log is read-only")

    _multi["log_decision"] = blow_up
    _assert_refused(_multi, _multi["handle"](_event()), "OSError: log is read-only")


def test_a_raise_in_run_members_refuses(_multi) -> None:
    def blow_up(*_args, **_kwargs):
        raise MemoryError("no threads")

    _multi["run_members"] = blow_up
    _assert_refused(_multi, _multi["handle"](_event()), "MemoryError: no threads")


def test_a_member_that_mutates_its_event_changes_no_other_members_verdict(_multi) -> None:
    mutated = threading.Event()
    seen = {}

    def evaluate_gate(argv, event, **_k):
        if argv[1].endswith("alpha.py"):
            event.command = "rm -rf x"
            event.raw["k"].append("tainted")
            event.tool = "Other"
            mutated.set()
            return None
        assert mutated.wait(10)
        seen["bravo"] = (event.command, event.tool, list(event.raw["k"]))
        return ("deny", "bravo saw the original")

    _multi["evaluate_gate"] = evaluate_gate
    _multi["gate_path_from_argv"] = lambda argv: Path(argv[1])
    original = _event()
    decision = _multi["handle"](original)
    assert decision is not None and decision.outcome == _multi["DENY"]
    assert "bravo saw the original" in decision.reason
    assert seen["bravo"] == ("ls", "Bash", ["v"])
    assert (original.command, original.tool, original.raw) == ("ls", "Bash", {"k": ["v"]})


def _write_index(tmp_path: Path, member: dict) -> tuple[str, str]:
    path = tmp_path / "index.json"
    path.write_text(json.dumps({"members": [member]}), encoding="utf-8")
    return str(path), _sha(path)


@pytest.mark.parametrize("bad", ["/etc/passwd", "../outside.py", "guards/../../outside.py", "C:\\x.py", "..\\x.py"])
def test_a_files_key_outside_the_root_refuses(tmp_path, bad) -> None:
    root = tmp_path / "root"
    root.mkdir()
    (tmp_path / "outside.py").write_text("x", encoding="utf-8")
    path, pin = _write_index(tmp_path, {"argv": ["--guard", "g.py"], "timeout": 5, "files": {bad: "0" * 64}})
    members, why = multi.load_index(path, pin, root)
    assert members is None
    assert "outside the repository root" in why


@pytest.mark.parametrize("bad", ["/etc/passwd", "../outside.py", "guards/../x.py", "C:\\x.py"])
def test_a_member_path_argument_outside_the_root_refuses(tmp_path, bad) -> None:
    path, pin = _write_index(tmp_path, {"argv": ["--guard", bad], "timeout": 5, "files": {}})
    members, why = multi.load_index(path, pin, tmp_path)
    assert members is None
    assert "outside the repository root" in why


def test_relative_member_paths_still_load(tmp_path) -> None:
    (tmp_path / "guards").mkdir()
    guard = tmp_path / "guards" / "g.py"
    guard.write_text("x", encoding="utf-8")
    path, pin = _write_index(
        tmp_path, {"argv": ["--guard", "guards/g.py"], "timeout": 5, "files": {"guards/g.py": _sha(guard)}}
    )
    assert multi.load_index(path, pin, tmp_path)[1] is None
