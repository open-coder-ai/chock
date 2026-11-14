"""Ruling 9: every child interpreter the shared runtime starts is isolated; hostile PYTHON* values change no verdict."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from managed_emit_helpers import bundle_hook, env_for, make_repo, run_hook

from chock.doctor.payloads import payload
from chock.gate import budget
from chock.hooks import launch

CANARY = "git commit --no-verify -m x"
HARMLESS = "git status"
#: Each variable the review proved or suspected: ends the guard early, breaks its start-up, or drops its folder.
POSIX_GIT = pytest.mark.skipif(sys.platform == "win32" or not shutil.which("git"), reason="POSIX sh and git")
HOSTILE = ("PYTHONPATH", "PYTHONHOME", "PYTHONPLATLIBDIR", "PYTHONSAFEPATH", "PYTHONSTARTUP")


def hostile_value(name: str, evil: Path) -> str:
    return {
        "PYTHONPATH": str(evil),
        "PYTHONHOME": str(evil / "no-such-home"),
        "PYTHONPLATLIBDIR": "nope",
        "PYTHONSAFEPATH": "1",
        "PYTHONSTARTUP": str(evil / "sitecustomize.py"),
    }[name]


@pytest.fixture
def evil(tmp_path: Path) -> Path:
    """A folder whose sitecustomize ends any interpreter that loads it with exit 0 and no decision."""
    folder = tmp_path / "evil"
    folder.mkdir()
    (folder / "sitecustomize.py").write_text("import os\nos._exit(0)\n", encoding="utf-8")
    return folder


@pytest.fixture
def bundle(tmp_path: Path) -> tuple[Path, dict]:
    return bundle_hook(make_repo(tmp_path), tmp_path)


def project_hook(scripts: Path, command: str, cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess:
    """The project entry (`claude_code.py --guard ...`) started isolated, so only its children see `env`'s PYTHON*."""
    return subprocess.run(
        [sys.executable, "-I", str(scripts / "claude_code.py"), "--guard", str(scripts / "block-no-verify.py")],
        input=json.dumps(payload("claude_code", command, cwd.as_posix())),
        capture_output=True,
        text=True,
        cwd=cwd,
        env=env,
        check=False,
        timeout=60,
    )


def assert_verdicts(denied: subprocess.CompletedProcess, allowed: subprocess.CompletedProcess) -> None:
    assert denied.returncode == allowed.returncode == 0, denied.stderr + allowed.stderr
    assert '"permissionDecision": "deny"' in denied.stdout, denied.stdout + denied.stderr
    assert "permissionDecision" not in allowed.stdout, allowed.stdout + allowed.stderr


@pytest.mark.parametrize("name", HOSTILE)
def test_managed_route_ignores_hostile_python_variables(name, bundle, evil, tmp_path) -> None:
    """The reviewer's proof (t_batch1.py section 5): the canary is still refused, a harmless call still allowed."""
    _, hook = bundle
    env = env_for(tmp_path, **{name: hostile_value(name, evil)})
    assert_verdicts(run_hook(hook, CANARY, tmp_path, env), run_hook(hook, HARMLESS, tmp_path, env))


@pytest.mark.parametrize("name", HOSTILE)
def test_project_route_children_ignore_hostile_python_variables(name, bundle, evil, tmp_path) -> None:
    """The project entry hands the guard child the same hostile environment; the child is isolated all the same."""
    root, _ = bundle
    scripts = root / "block-no-verify" / "scripts"
    env = env_for(tmp_path, **{name: hostile_value(name, evil)})
    assert_verdicts(project_hook(scripts, CANARY, tmp_path, env), project_hook(scripts, HARMLESS, tmp_path, env))


def test_isolated_child_drops_every_python_variable_and_keeps_bytecode_off(tmp_path: Path) -> None:
    script = tmp_path / "s.py"
    argv, env = budget.isolated_child(
        [sys.executable, script, "a"], {"PYTHONPATH": "x", "pythonhome": "y", "PATH": "/bin", "HOME": "/h"}
    )
    assert argv[:2] == [sys.executable, "-I"] and argv[-2:] == [str(script), "a"]
    assert env == {"PATH": "/bin", "HOME": "/h", **budget.BYTECODE_OFF}


def test_an_isolated_child_imports_from_its_own_folder_only(tmp_path: Path, evil: Path) -> None:
    """Its own folder is on sys.path (a guard's chock_shellparse), the current folder and PYTHONPATH are not."""
    own = tmp_path / "own"
    own.mkdir()
    (own / "helper.py").write_text("WHO = 'own'\n", encoding="utf-8")
    (evil / "helper.py").write_text("WHO = 'evil'\n", encoding="utf-8")
    (own / "main.py").write_text("import sys, helper\nprint(helper.WHO, sys.argv[1:])\n", encoding="utf-8")
    argv, env = budget.isolated_child([sys.executable, own / "main.py", "x y"], dict(os.environ))
    done = subprocess.run(
        argv, env={**env, "PYTHONPATH": str(evil)}, cwd=evil, capture_output=True, text=True, check=False
    )
    assert done.stdout.strip() == "own ['x y']", done.stderr


def launched(folder: Path, command: str, cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess:
    """The runtime in `folder` started through chock's launcher, as a project or plugin hook command starts it."""
    return subprocess.run(
        [
            "sh",
            str(folder / "launch.sh"),
            str(folder / "claude_code.py"),
            "--guard",
            str(folder / "block-no-verify.py"),
        ],
        input=json.dumps(payload("claude_code", command, cwd.as_posix())),
        capture_output=True,
        text=True,
        cwd=cwd,
        env=env,
        check=False,
        timeout=60,
    )


@POSIX_GIT
@pytest.mark.parametrize("route", ["project", "plugin"])
@pytest.mark.parametrize("name", [None, *HOSTILE])
def test_the_launcher_starts_the_runtime_isolated(route, name, bundle, evil, tmp_path) -> None:
    """Ruling 9 on the launcher routes: the outer interpreter is isolated too, before and with each hostile value."""
    root, _ = bundle
    work = tmp_path / "work"
    subprocess.run(["git", "init", "-q", str(work)], check=True)
    folder = work / ".chock" / "bin" if route == "project" else tmp_path / "plugin" / "scripts"
    shutil.copytree(root / "block-no-verify" / "scripts", folder)
    (folder / "launch.sh").write_text(launch.launcher_text(), encoding="utf-8", newline="\n")
    env = env_for(tmp_path, **({} if name is None else {name: hostile_value(name, evil)}))
    assert_verdicts(launched(folder, CANARY, work, env), launched(folder, HARMLESS, work, env))
