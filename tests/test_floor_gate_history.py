"""Release gate G1, GT-1 history (S2), scenarios B1-B8: each test asserts the exit the plan owes.

A commit is named when it changes a plane path to a state that differs from the base's, even if the tree diff
base..head is empty for it."""

from __future__ import annotations

from floor_support import CLAUDE, base_repo, commit, git, run_floor, write
from floor_support4 import HOOKLESS, rebase_main

SETTINGS = ".claude/settings.json"
HISTORY_ONLY = "  (in a commit of the range only"
USER = ("-c", "user.name=t", "-c", "user.email=t@example.com")


def _named(repo, capsys, path, *extra):
    code, out = run_floor(repo, capsys, *extra)
    assert code == 1, out
    assert f"\n  {path}{HISTORY_ONLY}" in out, out
    return out


def _merge(repo, *branches):
    git(repo, *USER, "merge", "-q", "--no-ff", "--no-edit", *branches)


def _off_and_on(repo):
    write(repo, SETTINGS, HOOKLESS)
    commit(repo, "hooks off")
    write(repo, SETTINGS, CLAUDE)
    commit(repo, "hooks back on")


def test_b1_plane_file_changed_and_restored_is_1_named(tmp_path, capsys):
    repo = base_repo(tmp_path)
    _off_and_on(repo)
    _named(repo, capsys, SETTINGS)


def test_b2_change_and_restore_on_a_merged_side_branch_is_1(tmp_path, capsys):
    repo = base_repo(tmp_path)
    write(repo, "src/app.py", "VALUE = 2\n")
    commit(repo, "pr: ordinary")
    git(repo, "checkout", "-q", "-b", "side")
    _off_and_on(repo)
    git(repo, "checkout", "-q", "pr")
    _merge(repo, "side")
    _named(repo, capsys, SETTINGS)


def test_b3_plane_file_created_and_deleted_is_1(tmp_path, capsys):
    repo = base_repo(tmp_path)
    write(repo, ".claude/agents/helper.md", "# helper\n")
    commit(repo, "add an agent")
    git(repo, "rm", "-q", ".claude/agents/helper.md")
    commit(repo, "remove it")
    _named(repo, capsys, ".claude/agents/helper.md")


def test_b4_mode_only_change_and_its_revert_is_1(tmp_path, capsys):
    repo = base_repo(tmp_path)
    (repo / SETTINGS).chmod(0o755)
    commit(repo, "make it executable")
    (repo / SETTINGS).chmod(0o644)
    commit(repo, "and back")
    _named(repo, capsys, SETTINGS)


def test_b5_rename_into_a_plane_folder_and_back_out_is_1(tmp_path, capsys):
    repo = base_repo(tmp_path)
    git(repo, "mv", "src/app.py", ".claude/app.py")
    commit(repo, "move into the agent folder")
    git(repo, "mv", ".claude/app.py", "src/app.py")
    commit(repo, "move back")
    _named(repo, capsys, ".claude/app.py")


def _base_moves_on(repo):
    """main changes a plane file after `pr` branched; the pull request's own commits never touch the plane."""
    write(repo, "src/app.py", "VALUE = 2\n")
    commit(repo, "pr: ordinary")
    git(repo, "checkout", "-q", "main")
    write(repo, ".github/workflows/chock.yml", "name: changed on main\n")
    commit(repo, "main: workflow")


def test_b6_branch_that_merged_a_newer_base_is_0(tmp_path, capsys):
    repo = base_repo(tmp_path)
    _base_moves_on(repo)
    git(repo, "checkout", "-q", "pr")
    _merge(repo, "main")
    code, out = run_floor(repo, capsys)
    assert code == 0, out


def test_b6_branch_made_before_the_base_changed_judged_as_merge_result_is_0(tmp_path, capsys):
    repo = base_repo(tmp_path)
    _base_moves_on(repo)
    git(repo, "checkout", "-q", "-b", "merge-ref")
    _merge(repo, "pr")
    code, out = run_floor(repo, capsys, "--head", "merge-ref")
    assert code == 0, out


def test_b7_revert_of_an_unrelated_commit_is_0(tmp_path, capsys):
    repo = base_repo(tmp_path)
    rebase_main(repo, lambda r: write(r, "src/app.py", "VALUE = 5\n"))
    git(repo, *USER, "revert", "--no-edit", "HEAD")
    code, out = run_floor(repo, capsys)
    assert code == 0, out


def test_b7_cherry_pick_of_a_commit_outside_the_plane_is_0(tmp_path, capsys):
    repo = base_repo(tmp_path)
    git(repo, "checkout", "-q", "-b", "other")
    write(repo, "src/other.py", "OTHER = 1\n")
    picked = commit(repo, "other: source only")
    git(repo, "checkout", "-q", "pr")
    git(repo, *USER, "cherry-pick", picked)
    code, out = run_floor(repo, capsys)
    assert code == 0, out


def test_b8_octopus_merge_bringing_a_plane_change_reverted_later_is_1(tmp_path, capsys):
    repo = base_repo(tmp_path)
    for name, rel, content in (("a", SETTINGS, HOOKLESS), ("b", "src/b.py", "B = 1\n"), ("c", "src/c.py", "C = 1\n")):
        git(repo, "checkout", "-q", "-b", name, "pr")
        write(repo, rel, content)
        commit(repo, f"{name}: change")
    git(repo, "checkout", "-q", "pr")
    _merge(repo, "a", "b", "c")
    assert len(git(repo, "rev-parse", "HEAD^@").split()) == 4  # an octopus: pr and three branches
    write(repo, SETTINGS, CLAUDE)
    commit(repo, "revert the hooks change the octopus brought")
    _named(repo, capsys, SETTINGS)
