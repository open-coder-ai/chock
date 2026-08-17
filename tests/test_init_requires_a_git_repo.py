"""`init` must not claim enforcement it cannot deliver.

In a directory that is not a git repository, `init` printed "Initialized Chock",
exited 0, and created a `.git/hooks/` tree by side effect of `mkdir(parents=True)`. Git
never looks at that directory -- `git status` does not even work there -- so the adopter
walked away believing commits were gated when nothing could ever run. Of every failure mode
this project has, claiming enforcement that cannot fire is the one it treats as worst.

The second half of the file is the same mistake pointed the other way: `get_hooks_dir`
assumed `.git` was a directory. In a linked worktree it is a file, so hook installation
crashed and `--skip-hooks` became the only way to work there. Both come from guessing at
git's layout instead of asking git, so both are tested together.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from conftest import init_repo

from chock.hooks.install import get_hooks_dir, is_git_repo
from chock.hooks.install import main as install_hooks_main
from chock.scaffold.init import cmd_init


@pytest.fixture
def not_a_repo(tmp_path: Path) -> Path:
    plain = tmp_path / "plain"
    plain.mkdir()
    return plain


# ----------------------------------------------------------------- no fake .git is created
def test_init_creates_no_git_directory(not_a_repo: Path, capsys: pytest.CaptureFixture) -> None:
    assert cmd_init([str(not_a_repo)]) == 0
    assert not (not_a_repo / ".git").exists(), "init conjured a .git directory git will never read"


def test_init_says_enforcement_is_not_active(not_a_repo: Path, capsys: pytest.CaptureFixture) -> None:
    """Silence here is the defect: the adopter has no other signal that hooks are missing."""
    cmd_init([str(not_a_repo)])
    out = capsys.readouterr().out
    assert "not a git repository" in out
    assert "git init" in out, "the warning must say how to fix it"


def test_init_still_scaffolds(not_a_repo: Path) -> None:
    """Refusing to install hooks is not a reason to refuse the rest; the files are useful."""
    assert cmd_init([str(not_a_repo)]) == 0
    assert (not_a_repo / "AGENTS.md").exists()
    assert (not_a_repo / ".chock" / "config.yaml").exists()


def test_install_hooks_refuses_outside_a_repo(not_a_repo: Path, capsys: pytest.CaptureFixture) -> None:
    """The standalone command has no purpose without git, so it fails rather than pretends."""
    assert install_hooks_main([str(not_a_repo)]) == 1
    assert not (not_a_repo / ".git").exists()
    assert "not a git repository" in capsys.readouterr().err


# ------------------------------------------------------- guard the guard: hooks still install
def test_a_real_repo_still_gets_its_hooks(tmp_path: Path) -> None:
    """A skip that is unconditional would pass every assertion above and enforce nothing."""
    repo = init_repo(tmp_path)
    assert cmd_init([str(repo)]) == 0
    assert (repo / ".git" / "hooks" / "pre-commit").exists()
    assert list((repo / ".git" / "hooks" / "pre-commit.d").iterdir())


def test_a_subdirectory_of_a_repo_is_not_its_own_repo(tmp_path: Path) -> None:
    """`rev-parse` succeeds in a subdirectory, but its hooks live in the parent's .git.

    Accepting it would recreate the same dead `.git/hooks/` one level down.
    """
    repo = init_repo(tmp_path)
    nested = repo / "packages" / "app"
    nested.mkdir(parents=True)
    assert is_git_repo(repo)
    assert not is_git_repo(nested)


# ------------------------------------------------- the other layout git is free to choose
@pytest.fixture
def linked_worktree(tmp_path: Path) -> Path:
    """A `git worktree add` checkout, where `.git` is a file rather than a directory."""
    main = tmp_path / "main"
    main.mkdir()
    repo = init_repo(main)
    (repo / "seed.txt").write_text("seed\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-qm", "seed"], cwd=repo, check=True, capture_output=True)
    linked = tmp_path / "linked"
    subprocess.run(["git", "worktree", "add", "-q", str(linked), "-b", "feature"], cwd=repo, check=True)
    return linked


def test_a_linked_worktree_keeps_git_as_a_file(linked_worktree: Path) -> None:
    """Guard the guard: every assertion below is vacuous if the fixture is a plain clone."""
    assert (linked_worktree / ".git").is_file()


def test_hooks_land_where_git_says_they_do(linked_worktree: Path) -> None:
    """`repo_root/.git/hooks` is not a path that can exist here, so it was never right."""
    answer = subprocess.check_output(
        ["git", "rev-parse", "--git-path", "hooks"], cwd=linked_worktree, text=True
    ).strip()
    assert get_hooks_dir(linked_worktree).resolve() == Path(answer).resolve()


def test_install_hooks_succeeds_in_a_linked_worktree(linked_worktree: Path) -> None:
    """It crashed with NotADirectoryError, so `--skip-hooks` was the only way to work here."""
    assert install_hooks_main([str(linked_worktree)]) == 0
    assert (get_hooks_dir(linked_worktree) / "pre-commit").exists()


def test_core_hooks_path_is_still_honored(tmp_path: Path) -> None:
    """The hand-written special case for it is gone; `--git-path` must cover it instead."""
    repo = init_repo(tmp_path)
    subprocess.run(["git", "config", "core.hooksPath", ".myhooks"], cwd=repo, check=True)
    assert get_hooks_dir(repo).resolve() == (repo / ".myhooks").resolve()
