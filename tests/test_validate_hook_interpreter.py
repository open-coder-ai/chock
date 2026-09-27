"""The validate hook must find an interpreter that actually has chock in it."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from chock.hooks.install import INTERPRETER_PLACEHOLDER, get_hooks_dir, install_validate_hook

HOOK_NAME = "99-chock-validate"


@pytest.fixture
def installed_hook(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "--quiet"], cwd=repo, check=True)
    hooks_dir = get_hooks_dir(repo)
    hooks_dir.mkdir(parents=True, exist_ok=True)
    install_validate_hook(hooks_dir, repo)

    name = f"{HOOK_NAME}.ps1" if sys.platform == "win32" else HOOK_NAME
    return hooks_dir / "pre-commit.d" / name


def test_the_hook_does_not_call_a_bare_python(installed_hook: Path) -> None:
    """The defect itself: `python -m chock` with nothing choosing the interpreter."""
    body = installed_hook.read_text(encoding="utf-8")
    assert "python -m chock" not in body, "a bare `python` is whatever is first on PATH"


def test_the_installing_interpreter_is_baked_in(installed_hook: Path) -> None:
    """Whatever ran the installer can import chock -- that is the one to prefer."""
    body = installed_hook.read_text(encoding="utf-8")
    assert sys.executable in body
    assert INTERPRETER_PLACEHOLDER not in body, "the placeholder was never substituted"


def test_candidates_are_probed_for_the_package_not_merely_for_existing(installed_hook: Path) -> None:
    """A venv can be moved or rebuilt, so the baked path is a preference, not a guarantee."""
    body = installed_hook.read_text(encoding="utf-8")
    assert "import chock" in body


def test_a_missing_interpreter_fails_open(installed_hook: Path) -> None:
    """A guard that bricks the repo is worse than no guard."""
    body = installed_hook.read_text(encoding="utf-8")
    assert "exit 0" in body
    assert "validation skipped" in body


def test_the_installed_hook_has_lf_line_endings(installed_hook: Path) -> None:
    """A shell script with CRLF dies on Linux with `bad interpreter: /usr/bin/env bash^M`."""
    assert b"\r\n" not in installed_hook.read_bytes()


@pytest.mark.skipif(sys.platform == "win32", reason="bash hook variant")
def test_a_stale_baked_interpreter_falls_back_instead_of_breaking(installed_hook: Path) -> None:
    """The baked interpreter is the one absolute path the hook keeps, so it must be soft."""
    body = installed_hook.read_text(encoding="utf-8")
    installed_hook.write_text(body.replace(sys.executable, "/nonexistent/python"), encoding="utf-8", newline="\n")

    repo = installed_hook.parents[3]
    proc = subprocess.run(["bash", str(installed_hook)], cwd=str(repo), capture_output=True, text=True, check=False)
    assert proc.returncode == 0, f"a stale interpreter path broke the hook:\n{proc.stdout}\n{proc.stderr}"


@pytest.mark.skipif(sys.platform == "win32", reason="bash hook variant")
def test_the_hook_runs_and_allows_a_clean_repo(installed_hook: Path, tmp_path: Path) -> None:
    """Executed, not merely inspected -- the original defect passed every inspection."""
    bash = "bash"
    repo = installed_hook.parents[3]
    proc = subprocess.run([bash, str(installed_hook)], cwd=str(repo), capture_output=True, text=True, check=False)
    assert proc.returncode == 0, f"the hook blocked a clean repo:\n{proc.stdout}\n{proc.stderr}"
    assert "No module named chock" not in (proc.stdout + proc.stderr)


POWERSHELL_HOOK = Path(__file__).resolve().parents[1] / "src" / "chock" / "hooks" / "data" / "pre-commit.ps1"


def test_the_powershell_probe_cannot_end_the_hook_on_a_missing_candidate() -> None:
    """Under "Stop", PS 5.1 makes `& <missing> 2>$null` a terminating error: the commit was blocked."""
    body = POWERSHELL_HOOK.read_text(encoding="utf-8")
    loop = body[
        body.index("foreach ($candidate") : body.index('$ErrorActionPreference = "Stop"', body.index("foreach"))
    ]
    probe_start = body.index("foreach ($candidate")
    assert body.rindex('$ErrorActionPreference = "Continue"', 0, probe_start) > body.index('= "Stop"')
    assert "Get-Command $candidate -ErrorAction SilentlyContinue" in loop
    assert "try {" in loop and "} catch {" in loop
    assert loop.index("Get-Command") < loop.index("& $candidate"), "resolve before invoking"


@pytest.mark.skipif(not (shutil.which("pwsh") or shutil.which("powershell")), reason="no PowerShell here")
def test_the_powershell_hook_survives_a_stale_baked_interpreter(installed_hook: Path, tmp_path: Path) -> None:
    body = POWERSHELL_HOOK.read_text(encoding="utf-8").replace("@CHOCK_PYTHON@", str(tmp_path / "gone" / "python.exe"))
    hook = tmp_path / "hook.ps1"
    hook.write_text(body, encoding="utf-8")
    shell = shutil.which("pwsh") or shutil.which("powershell")
    repo = installed_hook.parents[3]
    proc = subprocess.run(
        [shell, "-NoProfile", "-File", str(hook)], cwd=repo, capture_output=True, text=True, check=False
    )
    assert "is not recognized" not in proc.stderr + proc.stdout
