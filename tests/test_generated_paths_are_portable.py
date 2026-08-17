"""Nothing Chock generates may hardcode the path it was generated at.

A wrapper containing an absolute path breaks the moment the repo is moved, renamed, or
mounted at a different prefix in a container -- and it breaks by *blocking commits*, since
a hook that cannot find its script exits non-zero. The installed policy wrapper did exactly
this, and on Windows it embedded a backslash path inside a `/bin/sh` script, where
backslashes are literal characters rather than separators:

    bash 'C:\\Users\\me\\repo\\.chock\\compiled\\...\\git-pre-commit.sh' "$@"

The check is empirical rather than a reading of the emitters: generate everything into a
throwaway repo, then look for that repo's own path in the output. That catches the class
however it is produced, including by code written later.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from chock.hooks.install import get_hooks_dir, install_policy_hooks, install_validate_hook

# `.git/objects` and friends are binary and contain hashes, not paths.
_SKIP_DIRS = {"objects", "refs", "logs", "info"}


def _generated_files(repo: Path) -> list[Path]:
    out: list[Path] = []
    for path in repo.rglob("*"):
        if not path.is_file():
            continue
        parts = set(path.relative_to(repo).parts)
        if parts & _SKIP_DIRS:
            continue
        out.append(path)
    return out


def _forms(path: Path) -> list[str]:
    """The spellings of an absolute path that could end up in a generated file."""
    text = str(path)
    forms = {text, text.replace("\\", "/")}
    drive, _, rest = text.partition(":")
    if len(drive) == 1:  # C:\... -> /c/... as MSYS bash renders it
        forms.add(f"/{drive.lower()}{rest}".replace("\\", "/"))
    return sorted(forms)


@pytest.fixture
def wired_repo(tmp_path: Path) -> Path:
    """A repo with the full hook set installed, at a path we can search for."""
    repo = tmp_path / "project"
    repo.mkdir()
    subprocess.run(["git", "init", "--quiet"], cwd=repo, check=True)

    # A compiled gate to wrap. Built directly so this test does not depend on `init`.
    from conftest import baseline_policy

    from chock.compile.compiler import compile_policy
    from chock.compile.surfaces import Surface

    compile_policy(
        baseline_policy("protect-main-branch"),
        targets=[Surface.GIT_HOOK.value],
        output_root=repo / ".chock" / "compiled",
    )

    hooks_dir = get_hooks_dir(repo)
    hooks_dir.mkdir(parents=True, exist_ok=True)
    install_validate_hook(hooks_dir, repo)
    install_policy_hooks(repo, hooks_dir)
    return repo


def test_no_generated_file_embeds_the_repo_path(wired_repo: Path) -> None:
    needles = _forms(wired_repo)
    offenders: list[str] = []
    for path in _generated_files(wired_repo):
        try:
            body = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if any(needle in body for needle in needles):
            offenders.append(str(path.relative_to(wired_repo)))
    assert not offenders, (
        "these generated files hardcode the repo path and will break when it moves: "
        f"{sorted(offenders)}. Resolve the repo root at run time instead "
        "(`git rev-parse --show-toplevel`), or locate siblings from $0."
    )


def test_the_scan_covers_the_hooks_it_claims_to(wired_repo: Path) -> None:
    """Guard the guard: the rule is vacuous if nothing was installed to inspect."""
    hooks = list((get_hooks_dir(wired_repo) / "pre-commit.d").iterdir())
    names = sorted(p.name for p in hooks)
    assert any(n.startswith("50-chock-policy-") for n in names), names
    assert any(n.startswith("99-chock-validate") for n in names), names


def test_a_policy_wrapper_has_no_backslash_path(wired_repo: Path) -> None:
    """In a POSIX shell a backslash is an escape, not a separator."""
    for wrapper in (get_hooks_dir(wired_repo) / "pre-commit.d").glob("50-chock-policy-*"):
        body = wrapper.read_text(encoding="utf-8")
        assert "\\" not in body, f"{wrapper.name} embeds a Windows-style path: {body}"


@pytest.mark.skipif(sys.platform == "win32", reason="the sh wrapper is the POSIX variant")
def test_a_policy_wrapper_still_runs_after_the_repo_moves(wired_repo: Path) -> None:
    """The point of the whole rule, executed rather than inspected."""
    moved = wired_repo.parent / "project-renamed"
    wired_repo.rename(moved)

    wrapper = next((get_hooks_dir(moved) / "pre-commit.d").glob("50-chock-policy-*"))
    proc = subprocess.run(["sh", str(wrapper)], cwd=str(moved), capture_output=True, text=True, check=False)
    # protect-main-branch blocks commits on main, so exit 1 is a correct verdict. What must
    # not happen is the shell failing to find the script at all.
    assert "No such file" not in (proc.stdout + proc.stderr), proc.stderr
    assert proc.returncode in (0, 1), f"wrapper broke after the move:\n{proc.stdout}\n{proc.stderr}"
