"""The validate hook must find an interpreter that actually has chock in it.

The hook ran a bare `python`. chock is normally installed into a virtualenv, so a
bare `python` resolves to whatever is first on PATH -- a different interpreter, without the
package. Every commit then died with "No module named chock", so the hook blocked the
repo instead of validating it.

This was invisible locally, because the developer's ambient python happened to be able to
import chock. It surfaced the first time the acceptance suite ran on a clean Linux
runner, failing exactly the three scenarios that assert ordinary work still commits.
"""

from __future__ import annotations

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
    """A venv can be moved or rebuilt, so the baked path is a preference, not a guarantee.

    Probing `import chock` rather than `-c ''` is the whole point: an interpreter
    that runs is not the same as an interpreter that has the package.
    """
    body = installed_hook.read_text(encoding="utf-8")
    assert "import chock" in body


def test_a_missing_interpreter_fails_open(installed_hook: Path) -> None:
    """A guard that bricks the repo is worse than no guard.

    "No interpreter" means the check did not happen, which is not a policy violation. It
    must say so and let the commit through, the same way the PreToolUse adapter does.
    """
    body = installed_hook.read_text(encoding="utf-8")
    assert "exit 0" in body
    assert "validation skipped" in body


def test_the_installed_hook_has_lf_line_endings(installed_hook: Path) -> None:
    """A shell script with CRLF dies on Linux with `bad interpreter: /usr/bin/env bash^M`.

    The hook is one of the few generated files that is *executed*, so "git normalises it on
    commit" does not save us -- it runs straight from the working tree, on the adopter's
    machine. `write_text` without `newline=` emits CRLF on Windows.
    """
    assert b"\r\n" not in installed_hook.read_bytes()


@pytest.mark.skipif(sys.platform == "win32", reason="bash hook variant")
def test_a_stale_baked_interpreter_falls_back_instead_of_breaking(installed_hook: Path) -> None:
    """The baked interpreter is the one absolute path the hook keeps, so it must be soft.

    A virtualenv can be deleted or rebuilt at a new path. Unlike a hardcoded *script* path,
    which simply breaks, this one is only the first candidate: the probe moves on. That
    distinction is what makes keeping it defensible, so it is checked rather than asserted.
    """
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
