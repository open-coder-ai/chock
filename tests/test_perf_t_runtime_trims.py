"""PERF-T: the runtime loader runs the bytes it hashed, and one process reads each committed file once."""

from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import init_repo
from runtime_support import write_runtime

from chock.gate import runtime_bundle
from chock.gate.runner import actor, context, headread

_ENTRY = "claude_code"


def _entry(tmp_path: Path, shared_text: str | None = None, *, pin: bool = True) -> Path:
    entry = write_runtime(tmp_path / f"{_ENTRY}.py", _ENTRY)
    shared = entry.with_name(runtime_bundle.SHARED_FILE)
    if shared_text is not None:
        shared.write_text(shared_text, encoding="utf-8")
        if pin:
            old = runtime_bundle.shared_pin()
            new = hashlib.sha256(shared_text.replace("\r\n", "\n").encode()).hexdigest()
            entry.write_text(entry.read_text(encoding="utf-8").replace(old, new), encoding="utf-8")
    return entry


def _fault(entry: Path, cwd: Path | None = None) -> str | None:
    code = (
        "import sys, runpy\n"
        f"ns = runpy.run_path({str(entry)!r}, run_name='under_test')\n"
        "print(ns['_CHOCK_RUNTIME_FAULT'])\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=False, cwd=cwd or entry.parent
    )
    assert proc.returncode == 0, proc.stderr
    return proc.stdout.strip()


def test_the_happy_path_binds_the_shared_names(tmp_path: Path) -> None:
    assert _fault(_entry(tmp_path)) == "None"


def test_a_pin_mismatch_refuses_before_running_anything(tmp_path: Path) -> None:
    entry = _entry(tmp_path, "open('ran.marker', 'w').close()\n", pin=False)
    fault = _fault(entry)
    assert "is not the version this entry was built with" in fault
    assert not (entry.parent / "ran.marker").exists()


def test_a_missing_shared_file_refuses(tmp_path: Path) -> None:
    entry = _entry(tmp_path)
    entry.with_name(runtime_bundle.SHARED_FILE).unlink()
    fault = _fault(entry)
    assert "chock could not load" in fault
    assert "FileNotFoundError" in fault


def test_a_module_body_that_exits_refuses(tmp_path: Path) -> None:
    fault = _fault(_entry(tmp_path, "import sys\nsys.exit(0)\n"))
    assert "chock could not load" in fault
    assert "SystemExit" in fault


def test_the_loader_does_not_import_inspect(tmp_path: Path) -> None:
    entry = _entry(tmp_path)
    code = f"import sys, runpy\nrunpy = runpy.run_path({str(entry)!r}, run_name='t')\nprint('inspect' in sys.modules)\n"
    base = subprocess.run(
        [sys.executable, "-I", "-c", "import sys, runpy; print('inspect' in sys.modules)"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert base.stdout.strip() == "False", "runpy alone must not load inspect"
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=False)
    assert proc.stdout.strip() == "False", proc.stderr


def _counting(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    real = subprocess.run
    calls: list[list[str]] = []

    def run(argv, *args, **kwargs):
        calls.append(list(argv))
        return real(argv, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", run)
    return calls


def _committed(tmp_path: Path) -> Path:
    repo = init_repo(tmp_path)
    (repo / ".chock").mkdir()
    (repo / ".chock" / "config.yaml").write_text("rollout: observe\n", encoding="utf-8")
    (repo / "a.txt").write_text("one\r\ntwo\n", encoding="utf-8", newline="")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "c", "--no-gpg-sign"], cwd=repo, check=True)
    return repo


def _shows(calls: list[list[str]]) -> int:
    return sum(1 for argv in calls if "show" in argv)


def test_one_write_evaluation_spawns_git_once_per_committed_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _committed(tmp_path)
    calls = _counting(monkeypatch)
    ctx = context.WriteContext(repo, {"a.txt": "x\n"})
    for _ in range(4):
        assert ctx.committed_blob("a.txt") == "one\ntwo\n"
    for _ in range(10):
        assert actor.committed_rollout(repo, "HEAD") == "observe"
    assert _shows(calls) == 2, "before this change the same reads spawned 14 `git show` processes"
    assert len(calls) == 3, "one rev-parse resolves HEAD for the whole process"


def test_a_failure_is_read_once_and_stays_a_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _committed(tmp_path)
    calls = _counting(monkeypatch)
    ctx = context.WriteContext(repo, {})
    assert [ctx.committed_blob("missing.txt") for _ in range(3)] == ["", "", ""]
    assert _shows(calls) == 1


def test_no_commit_yet_reads_as_before(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    assert context.WriteContext(repo, {}).committed_blob("a.txt") == ""
    assert actor.committed_rollout(repo, "HEAD") == "enforce"


def test_a_new_head_is_read_afresh_after_forgetting(tmp_path: Path) -> None:
    repo = _committed(tmp_path)
    ctx = context.WriteContext(repo, {})
    assert ctx.committed_blob("a.txt") == "one\ntwo\n"
    (repo / "a.txt").write_text("three\n", encoding="utf-8")
    subprocess.run(["git", "commit", "-qam", "d", "--no-gpg-sign"], cwd=repo, check=True)
    headread._head_forget()
    assert ctx.committed_blob("a.txt") == "three\n"
