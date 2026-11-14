"""Release gate G1, GT-1 links (S1), scenarios A7-A11: each test asserts the exit the plan owes."""

from __future__ import annotations

import time

from floor_support import CLAUDE, base_repo, commit, git, run_floor, write
from floor_support4 import FAKE_A, FAKE_B, gitlink, raw_commit, rebase_main, rm, symlink, undecided
from test_floor_gate_links import pr_source, raw_base

A11_LINKS = 2000
A11_SECONDS = 60  # an explicit bound in place of a suite-wide pytest timeout, which this repository does not set


def test_a7_link_at_an_ancestor_of_a_root_anchored_pattern_is_2(tmp_path, capsys):
    """`.github -> gh`: the client opens gh/workflows/** as .github/workflows/**, and gh/ is not plane."""
    repo = base_repo(tmp_path)

    def base(r):
        (r / ".github").rename(r / "gh")
        symlink(r, ".github", "gh")

    rebase_main(repo, base)
    pr_source(repo)
    out = undecided(repo, capsys, ".github")
    assert "opens gh, which is not control plane" in out, out


def test_a7_link_whose_target_tree_holds_an_agent_folder_is_0(tmp_path, capsys):
    """`pkg -> real` with `real/.claude/`: real/.claude/** is plane by itself, so the link opens only plane paths."""
    repo = base_repo(tmp_path)

    def base(r):
        write(r, "real/.claude/settings.json", CLAUDE)
        symlink(r, "pkg", "real")

    rebase_main(repo, base)
    pr_source(repo)
    code, out = run_floor(repo, capsys)
    assert code == 0, out


def test_a8_plane_folder_replaced_by_a_link_to_an_identical_copy_is_nonzero(tmp_path, capsys):
    repo = base_repo(tmp_path)
    write(repo, "copy/claude/settings.json", CLAUDE)
    rm(repo, ".claude")
    symlink(repo, ".claude", "copy/claude")
    commit(repo, "pr: the agent folder becomes a link to the same bytes")
    code, out = run_floor(repo, capsys)
    assert code != 0, out
    assert ".claude" in out, out


def test_a9_ordinary_link_to_a_plane_file_is_0(tmp_path, capsys):
    repo = base_repo(tmp_path)
    symlink(repo, "docs/s", "../.claude/settings.json")
    write(repo, "src/app.py", "VALUE = 2\n")
    commit(repo, "pr: a docs link to the settings file")
    code, out = run_floor(repo, capsys)
    assert code == 0, out


def test_a10_submodule_added_at_a_plane_path_is_1_named(tmp_path, capsys):
    repo = base_repo(tmp_path)
    gitlink(repo, ".claude/shared", FAKE_A)
    raw_commit(repo, "pr: add a submodule in the agent folder")
    code, out = run_floor(repo, capsys)
    assert code == 1, out
    assert "\n  .claude/shared\n" in out, out


def _base_submodule(repo):
    raw_base(repo, lambda r: gitlink(r, ".claude/shared", FAKE_A))


def test_a10_unchanged_submodule_inside_the_plane_is_0(tmp_path, capsys):
    repo = base_repo(tmp_path)
    _base_submodule(repo)
    pr_source(repo)
    code, out = run_floor(repo, capsys)
    assert code == 0, out


def test_a10_moved_submodule_pointer_inside_the_plane_is_1_named(tmp_path, capsys):
    repo = base_repo(tmp_path)
    _base_submodule(repo)
    gitlink(repo, ".claude/shared", FAKE_B)
    raw_commit(repo, "pr: bump the submodule")
    code, out = run_floor(repo, capsys)
    assert code == 1, out
    assert "\n  .claude/shared\n" in out, out


def test_a11_two_thousand_plane_links_within_the_plane_is_0_in_bounded_time(tmp_path, capsys):
    repo = base_repo(tmp_path)

    def base(r):
        write(r, ".codex/settings.json", CLAUDE)
        for i in range(A11_LINKS):
            symlink(r, f".claude/links/l{i:04d}", "../../.codex/settings.json")

    rebase_main(repo, base)
    assert len(git(repo, "ls-files", ".claude/links").splitlines()) == A11_LINKS
    pr_source(repo)
    start = time.monotonic()
    code, out = run_floor(repo, capsys)
    elapsed = time.monotonic() - start
    print(f"A11: {A11_LINKS} links, exit {code} in {elapsed:.1f}s")
    assert code == 0, out[-800:]
    assert elapsed < A11_SECONDS, elapsed
