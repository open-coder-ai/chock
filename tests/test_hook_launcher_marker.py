"""The launcher runs the runtime itself and reads its start marker; a candidate with none passes to the next."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import bash_executable
from test_hook_launcher import _PROBE_REL, _bin_dir, _failing, _probe, _repo, _run, posix_only

from chock.hooks.launch import hook_command


def _marker_runtime(repo: Path, body: str) -> None:
    """A runtime that writes the real start-marker preamble, then `body`."""
    from chock.gate.runtime_bundle import _START_MARKER

    (repo / _PROBE_REL).write_text(_START_MARKER + body, encoding="utf-8")


def _script(bin_dir: Path, name: str, text: str) -> None:
    stub = bin_dir / name
    stub.write_text(text, encoding="utf-8")
    stub.chmod(0o755)


@posix_only
@pytest.mark.parametrize(
    "stub",
    [
        "#!/bin/sh\nexit 9009\n",
        "#!/bin/sh\nexit 127\n",
        "#!/bin/sh\nexit 0\n",
        "#!/bin/sh\necho 'SyntaxError' >&2\nexit 1\n",
    ],
    ids=["9009", "127", "stub-exit-0", "syntax-error-on-old-python"],
)
def test_a_candidate_that_writes_no_marker_passes_to_the_next(tmp_path: Path, stub: str) -> None:
    repo = _repo(tmp_path)
    bin_dir = _bin_dir(tmp_path, "bin", python=sys.executable)
    _script(bin_dir, "python3", stub)
    assert _probe(_run(repo, repo, path=str(bin_dir)))["exe"] == str(bin_dir / "python")


@posix_only
def test_a_python_below_the_minimum_passes_to_the_next(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _marker_runtime(repo, "import sys\nprint('ran')\n")
    bin_dir = _bin_dir(tmp_path, "bin", python=sys.executable)
    _script(
        bin_dir,
        "python3",
        f"#!/bin/sh\nexec {sys.executable} -c 'import sys,runpy; sys.version_info=(3,10); runpy.run_path(sys.argv[1])' \"$3\"\n",
    )
    proc = _run(repo, repo, path=str(bin_dir))
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == "ran\n", "the 3.10 stand-in exited before running the body; the next candidate ran it once"


@posix_only
def test_a_candidate_that_wrote_the_marker_and_failed_is_not_retried(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _marker_runtime(repo, "import sys\nprint('once')\nsys.exit(7)\n")
    bin_dir = _bin_dir(tmp_path, "bin", python3=sys.executable, python=sys.executable)
    proc = _run(repo, repo, path=str(bin_dir))
    assert proc.returncode == 7
    assert proc.stdout == "once\n"


@posix_only
def test_a_runtime_that_raises_after_the_marker_keeps_its_own_exit(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _marker_runtime(repo, "raise RuntimeError('boom')\n")
    bin_dir = _bin_dir(tmp_path, "bin", python3=sys.executable, python=sys.executable)
    proc = _run(repo, repo, path=str(bin_dir))
    assert proc.returncode == 1
    assert "boom" in proc.stderr


@posix_only
def test_no_marker_from_any_candidate_refuses_with_todays_message(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    bin_dir = _bin_dir(tmp_path, "bin")
    for name in ("python3", "python", "py"):
        _script(bin_dir, name, "#!/bin/sh\nexit 0\n")
    proc = _run(repo, repo, path=str(bin_dir))
    assert proc.returncode == 2
    assert proc.stdout == ""
    assert proc.stderr.startswith("chock: no working Python 3.11+ found (tried chock.python, python3, python, py)")


@posix_only
def test_the_runtime_keeps_stdin_and_stdout_after_a_failed_candidate(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _marker_runtime(repo, "import sys\nprint(sys.stdin.read().upper())\n")
    bin_dir = _bin_dir(tmp_path, "bin", python=sys.executable)
    _failing(bin_dir, "python3")
    proc = subprocess.run(
        [bash_executable(), "-c", hook_command(_PROBE_REL)],
        cwd=repo,
        env={**os.environ, "PATH": str(bin_dir)},
        input="hook payload",
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.stdout == "HOOK PAYLOAD\n"


@posix_only
def test_the_windows_probe_path_is_kept_where_the_environment_says_windows(tmp_path: Path) -> None:
    """OS=Windows_NT selects the unchanged probe: a runtime with no marker still runs."""
    repo = _repo(tmp_path)
    (repo / _PROBE_REL).write_text("print('legacy')\n", encoding="utf-8")
    bin_dir = _bin_dir(tmp_path, "bin", python3=sys.executable)
    env = {**os.environ, "PATH": str(bin_dir), "OS": "Windows_NT"}
    proc = subprocess.run(
        [bash_executable(), "-c", hook_command(_PROBE_REL)],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.stdout == "legacy\n"


_JSON_ONLY = 'import sys\nprint(\'{"decision": "allow"}\')\n'


@posix_only
@pytest.mark.parametrize("fd", ["1", "2"])
@pytest.mark.parametrize("env_extra", [{}, {"MSYSTEM": "MINGW64"}], ids=["posix", "legacy-msystem"])
def test_an_inherited_start_fd_never_reaches_the_hook_output(tmp_path: Path, fd: str, env_extra: dict) -> None:
    repo = _repo(tmp_path)
    _marker_runtime(repo, _JSON_ONLY)
    bin_dir = _bin_dir(tmp_path, "bin", python3=sys.executable)
    env = {**os.environ, "PATH": str(bin_dir), "CHOCK_START_FD": fd, **env_extra}
    proc = subprocess.run(
        [bash_executable(), "-c", hook_command(_PROBE_REL)],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == '{"decision": "allow"}\n'
    assert "chock-python" not in proc.stderr


@posix_only
def test_a_child_of_the_runtime_sees_no_start_fd(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _marker_runtime(
        repo,
        "import os, subprocess, sys\nsys.stdout.write(subprocess.run(['env'], capture_output=True, text=True).stdout)\n",
    )
    bin_dir = _bin_dir(tmp_path, "bin", python3=sys.executable)
    (bin_dir / "env").symlink_to(shutil.which("env"))
    proc = subprocess.run(
        [bash_executable(), "-c", hook_command(_PROBE_REL)],
        cwd=repo,
        env={**os.environ, "PATH": str(bin_dir)},
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert "CHOCK_START_FD" not in proc.stdout
