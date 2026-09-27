"""The committed hook launcher: one command form every agent runs, and the Python it picks."""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path, PurePath

import pytest
from conftest import FRAMEWORK_ROOT, baseline_policy, bash_executable, init_repo

from chock.compile.compiler import compile_policy
from chock.compile.surfaces import Surface
from chock.hooks import launch
from chock.hooks.launch import LAUNCHER_REL, PYTHON_CONFIG_KEY, hook_command, record_interpreter, write_launcher

posix_only = pytest.mark.skipif(sys.platform == "win32", reason="symlinked PATH shims are a POSIX construct")

#: A stand-in runtime: reports which interpreter ran it, from where, and with what.
_PROBE = (
    "import json, os, sys\n"
    "print(json.dumps({'exe': sys.executable, 'cwd': os.getcwd(), 'args': sys.argv[1:], 'utf8': sys.flags.utf8_mode}))\n"
)
_PROBE_REL = ".chock/bin/probe.py"


def _git_repo(tmp_path: Path) -> Path:
    (tmp_path / "repo").mkdir()
    return init_repo(tmp_path / "repo")


def _repo(tmp_path: Path) -> Path:
    repo = _git_repo(tmp_path)
    write_launcher(repo)
    (repo / _PROBE_REL).write_text(_PROBE, encoding="utf-8")
    return repo


def _bin_dir(tmp_path: Path, name: str, **links: str) -> Path:
    """A PATH directory holding git and sh plus `links` (name -> target), nothing else."""
    bin_dir = tmp_path / name
    bin_dir.mkdir()
    for tool in ("git", "sh"):
        found = shutil.which(tool)
        assert found, tool
        (bin_dir / tool).symlink_to(found)
    for link, target in links.items():
        (bin_dir / link).symlink_to(target)
    return bin_dir


def _failing(bin_dir: Path, name: str) -> None:
    """A `name` that exists on PATH but does not run, like Windows' python3 Store alias."""
    stub = bin_dir / name
    stub.write_text("#!/bin/sh\nexit 9009\n", encoding="utf-8")
    stub.chmod(0o755)


def _run(repo: Path, cwd: Path, path: str | None = None) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    if path is not None:
        env["PATH"] = path
    command = hook_command(_PROBE_REL, "--guard", "a/b.sh")
    return subprocess.run(
        [bash_executable(), "-c", command], cwd=cwd, env=env, capture_output=True, text=True, check=False
    )


def _probe(proc: subprocess.CompletedProcess) -> dict:
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return json.loads(proc.stdout)


def test_launcher_runs_the_runtime_from_the_repo_root_when_started_in_a_subdirectory(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    nested = repo / "a" / "b"
    nested.mkdir(parents=True)
    out = _probe(_run(repo, nested))
    assert Path(out["cwd"]).resolve() == repo.resolve()
    assert out["args"] == ["--guard", "a/b.sh"]
    assert out["utf8"] == 1, "the launcher runs Python with -X utf8"


@posix_only
def test_a_python3_that_does_not_run_is_skipped(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    bin_dir = _bin_dir(tmp_path, "bin", python=sys.executable)
    _failing(bin_dir, "python3")
    out = _probe(_run(repo, repo, path=str(bin_dir)))
    assert out["exe"] == str(bin_dir / "python"), "the failing python3 must be passed over"


@posix_only
def test_the_recorded_interpreter_is_preferred(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    recorded = _bin_dir(tmp_path, "recorded", python3=sys.executable) / "python3"
    bin_dir = _bin_dir(tmp_path, "bin", python3=sys.executable)
    subprocess.run(["git", "config", "--local", PYTHON_CONFIG_KEY, str(recorded)], cwd=repo, check=True)
    out = _probe(_run(repo, repo, path=str(bin_dir)))
    assert out["exe"] == str(recorded)


@posix_only
def test_a_stale_recorded_interpreter_falls_back_to_path(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    bin_dir = _bin_dir(tmp_path, "bin", python3=sys.executable)
    subprocess.run(["git", "config", "--local", PYTHON_CONFIG_KEY, "/no/such/python3"], cwd=repo, check=True)
    out = _probe(_run(repo, repo, path=str(bin_dir)))
    assert out["exe"] == str(bin_dir / "python3")


@posix_only
def test_no_python_anywhere_refuses_with_an_actionable_message(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    bin_dir = _bin_dir(tmp_path, "bin")
    proc = _run(repo, repo, path=str(bin_dir))
    assert proc.returncode == 2, "no Python must refuse (exit 2), never allow"
    assert proc.stdout == ""
    assert "no working Python" in proc.stderr
    assert "git config chock.python" in proc.stderr


def test_the_launcher_is_written_with_lf_and_the_exec_bit(tmp_path: Path) -> None:
    dest = write_launcher(tmp_path)
    assert dest == tmp_path / LAUNCHER_REL
    raw = dest.read_bytes()
    assert b"\r" not in raw
    assert raw.decode("utf-8") == launch.launcher_text()
    if sys.platform != "win32":
        assert dest.stat().st_mode & stat.S_IXUSR


def test_record_interpreter_writes_local_config_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    global_config = tmp_path / "global.gitconfig"
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(global_config))
    repo = _git_repo(tmp_path)
    assert record_interpreter(repo) is True
    local = subprocess.run(
        ["git", "config", "--local", "--get", PYTHON_CONFIG_KEY], cwd=repo, capture_output=True, text=True, check=True
    )
    assert local.stdout.strip() == PurePath(sys.executable).as_posix()
    assert not global_config.exists(), "the interpreter is this clone's, never the user's global config"
    status = subprocess.run(["git", "status", "--porcelain"], cwd=repo, capture_output=True, text=True, check=True)
    assert status.stdout == "", "nothing committable is written"


@pytest.mark.parametrize(
    "args",
    [(), ("--guard", ".agents/policies/p/implementations/g.sh"), ("--gate", ".chock/compiled/p/stop/gate.json")],
)
def test_hook_command_reads_the_same_under_every_shell(args: tuple[str, ...]) -> None:
    command = hook_command(".chock/bin/cursor.py", *args)
    assert command.startswith('git -c "alias.chock-hook=!sh .chock/bin/launch.sh" chock-hook .chock/bin/cursor.py')
    for char in ("$", "\\", "'"):
        assert char not in command, f"{char!r} is read differently by bash, PowerShell or cmd.exe"


#: Keys a PowerShell-only host reads: there the launcher is called with `&` and keeps its exit code.
_POWERSHELL_KEYS = {"powershell", "windows", "commandWindows"}
_POWERSHELL_WRAP = ("& ", "; exit $LASTEXITCODE")


def _unwrapped(key: str, command: str) -> str:
    """The launcher command inside a PowerShell-only field's `& ...; exit $LASTEXITCODE` wrapper."""
    head, tail = _POWERSHELL_WRAP
    if key in _POWERSHELL_KEYS and command.startswith(head) and command.endswith(tail):
        return command[len(head) : -len(tail)]
    return command


def _commands(node) -> list[str]:
    if isinstance(node, dict):
        keys = {"command", "bash", *_POWERSHELL_KEYS}
        own = [_unwrapped(k, v) for k, v in node.items() if k in keys and isinstance(v, str)]
        return own + [c for v in node.values() for c in _commands(v)]
    if isinstance(node, list):
        return [c for v in node for c in _commands(v)]
    return []


def test_this_repo_commits_only_launcher_form_hook_commands() -> None:
    """chock adopts itself: no committed vendor config or fragment names an interpreter."""
    listed = subprocess.run(
        ["git", "ls-files", "*.json"], cwd=FRAMEWORK_ROOT, capture_output=True, text=True, check=True
    ).stdout.split()
    checked = 0
    for rel in listed:
        if rel.startswith("tests/"):
            continue
        try:
            doc = json.loads((FRAMEWORK_ROOT / rel).read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        for command in _commands(doc):
            if ".chock/bin/" not in command:
                continue
            checked += 1
            assert command.startswith(launch._PREFIX), f"{rel}: {command}"
            assert "@CHOCK_PYTHON@" not in command and "$" not in command, f"{rel}: {command}"
    assert checked, "expected this repo's own wired hook commands"


def test_cursor_fail_closed_on_gates_and_not_on_stop(tmp_path: Path) -> None:
    out = tmp_path / ".chock" / "compiled"
    for policy in ("block-destructive-commands", "pin-github-actions"):
        compile_policy(
            baseline_policy(policy),
            targets=[Surface.PRE_TOOL_USE.value, Surface.STOP.value],
            output_root=out,
            agents=["cursor"],
            repo_root=tmp_path,
        )
    shell = json.loads((out / "block-destructive-commands" / "pre-tool-use" / "cursor-hooks.json").read_text())
    write = json.loads((out / "pin-github-actions" / "pre-tool-use" / "cursor-write-hooks.json").read_text())
    stop = json.loads((out / "pin-github-actions" / "stop" / "cursor-hooks.json").read_text())
    assert all(e.get("failClosed") is True for e in shell["beforeShellExecution"])
    assert all(e.get("failClosed") is True for e in write["preToolUse"])
    assert stop["stop"], "expected a stop entry"
    assert all("failClosed" not in e for e in stop["stop"])
