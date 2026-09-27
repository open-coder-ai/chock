"""Which bash runs a guard: Git's on Windows, never the WSL launcher, found once per process."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from chock.gate import guard_runner


@pytest.fixture(autouse=True)
def fresh_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(guard_runner, "_FOUND_BASH", {})


def _touch(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("", encoding="utf-8")
    return path


def _as_windows(monkeypatch: pytest.MonkeyPatch, which: dict[str, str]) -> None:
    """Take the Windows branch without swapping os.name, which pathlib itself reads."""
    monkeypatch.setattr(guard_runner, "_WINDOWS", os.name)
    monkeypatch.setattr(guard_runner.shutil, "which", which.get)


def test_windows_prefers_gits_own_bin_bash_and_skips_the_wsl_launcher(tmp_path, monkeypatch) -> None:
    git_root = tmp_path / "Git"
    launcher = _touch(git_root / "bin" / "bash.exe")
    inner = _touch(git_root / "usr" / "bin" / "bash.exe")
    wsl = _touch(tmp_path / "Windows" / "System32" / "bash.exe")
    _as_windows(monkeypatch, {"git": str(git_root / "cmd" / "git.exe"), "bash": str(wsl)})

    candidates = guard_runner.bash_candidates()

    assert candidates[:2] == [str(launcher), str(inner)], "bin/bash.exe before usr/bin/bash.exe"
    assert str(wsl) not in candidates, "System32's bash is the WSL launcher and cannot see the guard"


def test_windows_puts_gits_coreutils_on_the_guards_path(tmp_path, monkeypatch) -> None:
    git_root = tmp_path / "Git"
    launcher = _touch(git_root / "bin" / "bash.exe")
    _touch(git_root / "usr" / "bin" / "sed.exe")
    _as_windows(monkeypatch, {})

    path = guard_runner.interpreter_env(str(launcher))["PATH"]

    assert path.split(os.pathsep)[0] == str(git_root / "usr" / "bin")


def test_the_bash_probe_runs_once_per_process(tmp_path, monkeypatch) -> None:
    """`chock check` ran a probe per guard per case: 239 bash spawns for one check."""
    guard = _touch(tmp_path / "g.sh")
    spawns = []
    real_run = subprocess.run

    def counting(*args, **kwargs):
        spawns.append(args[0])
        return real_run(*args, **kwargs)

    monkeypatch.setattr(guard_runner.subprocess, "run", counting)
    first = guard_runner.find_bash(guard)
    assert first is not None
    assert guard_runner.find_bash(_touch(tmp_path / "other.sh")) == first
    assert len(spawns) == 1
