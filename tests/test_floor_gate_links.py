"""Release gate G1, GT-1 links (S1), scenarios A1-A6: each test asserts the exit the plan owes.

A link at or inside a control-plane folder must open a control-plane path, or nothing, at base and head; else the
run is undecided (2) naming the link. A7-A11 are in test_floor_gate_links2.py."""

from __future__ import annotations

import pytest
from floor_support import CLAUDE, base_repo, commit, git, run_floor, write
from floor_support4 import FAKE_A, gitlink, raw_commit, rebase_main, rm, symlink, undecided

PLANE_FILE = ".codex/settings.json"
LIMIT = 32  # control_plane._MAX_HOPS: the most links one resolution may pass


def pr_source(repo):
    """A pull request touching only source, staged by path so a hand-made index entry survives."""
    write(repo, "src/app.py", "VALUE = 2\n")
    git(repo, "add", "src/app.py")
    raw_commit(repo, "pr: source only")


def raw_base(repo, change):
    """`change(repo)` stages the base by hand (gitlinks, empty links); commit it on main, put `pr` on it."""
    git(repo, "checkout", "-q", "main")
    change(repo)
    raw_commit(repo, "base edit")
    git(repo, "checkout", "-q", "-B", "pr")


def test_a1_link_between_plane_folders_with_source_only_pr_is_0(tmp_path, capsys):
    repo = base_repo(tmp_path)

    def base(r):
        write(r, ".agents/skills/x/SKILL.md", "# x\n")
        symlink(r, ".claude/skills", "../.agents/skills")

    rebase_main(repo, base)
    pr_source(repo)
    code, out = run_floor(repo, capsys)
    assert code == 0, out


def test_a2_plane_link_to_ordinary_folder_at_base_is_2_naming_link_and_target(tmp_path, capsys):
    repo = base_repo(tmp_path)
    rebase_main(repo, lambda r: symlink(r, ".claude/x", "../src"))
    pr_source(repo)
    out = undecided(repo, capsys, ".claude/x")
    assert "opens src, which is not control plane" in out, out


def test_a3_plane_link_to_ordinary_folder_added_at_head_is_nonzero_naming_link(tmp_path, capsys):
    repo = base_repo(tmp_path)
    symlink(repo, ".claude/x", "../src")
    commit(repo, "pr: link the agent folder to source")
    code, out = run_floor(repo, capsys)
    assert code != 0, out
    assert ".claude/x" in out, out


def _link(r, link, target):
    if link == ".claude":
        rm(r, ".claude")
        git(r, "rm", "-q", "-r", "--cached", "--ignore-unmatch", ".claude")
    symlink(r, link, target)
    git(r, "add", "-A")


def _chain(r, link, up, count):
    """`link` -> c1 -> ... -> c<count-1> -> .codex: `count` links in all, ending at a real plane folder."""
    write(r, PLANE_FILE, CLAUDE)
    _link(r, link, f"{up}c1" if count > 1 else f"{up}.codex")
    for i in range(1, count):
        symlink(r, f"c{i}", f"c{i + 1}" if i < count - 1 else ".codex")
    git(r, "add", "-A")


def _empty(r, link, _up):
    _link(r, link, "placeholder")
    empty = r.parent / "empty"
    empty.write_bytes(b"")
    oid = git(r, "hash-object", "-w", str(empty))
    git(r, "update-index", "--cacheinfo", f"120000,{oid},{link}")


def _submodule(r, link, up):
    _link(r, link, f"{up}vendor/sub/x")
    gitlink(r, "vendor/sub", FAKE_A)


A4_UNRESOLVED = {
    "absolute": (lambda r, link, _up: _link(r, link, "/etc/agent"), "absolute or empty target '/etc/agent'"),
    "climbs-out": (lambda r, link, up: _link(r, link, f"{up}../outside"), "leaves the repository"),
    "loop": (lambda r, link, _up: _link(r, link, link.rsplit("/", 1)[-1]), f"more than {LIMIT} links"),
    "empty": (_empty, "absolute or empty target ''"),
    "submodule": (_submodule, "passes through the submodule vendor/sub"),
    "chain-over-limit": (lambda r, link, up: _chain(r, link, up, LIMIT + 1), f"more than {LIMIT} links"),
}
WHERE = {"at": (".claude", ""), "inside": (".claude/hooks", "../")}


@pytest.mark.parametrize("where", list(WHERE))
@pytest.mark.parametrize("case", list(A4_UNRESOLVED))
def test_a4_plane_link_that_cannot_resolve_is_2(tmp_path, capsys, case, where):
    build, why = A4_UNRESOLVED[case]
    link, up = WHERE[where]
    repo = base_repo(tmp_path)
    raw_base(repo, lambda r: build(r, link, up))
    pr_source(repo)
    out = undecided(repo, capsys, link)
    assert why in out, out


@pytest.mark.parametrize("where", list(WHERE))
def test_a4_chain_at_the_limit_ending_in_a_plane_path_is_0(tmp_path, capsys, where):
    link, up = WHERE[where]
    repo = base_repo(tmp_path)
    raw_base(repo, lambda r: _chain(r, link, up, LIMIT))
    pr_source(repo)
    code, out = run_floor(repo, capsys)
    assert code == 0, out


A5_SPELLINGS = {
    "dot-slash": "./../.agents/skills",
    "doubled-slashes": "..//.agents//skills",
    "trailing-slash": "../.agents/skills/",
    "climb-and-return": "../src/../.agents/skills",
    "case-only": "../.AGENTS/Skills",
}


@pytest.mark.parametrize("case", list(A5_SPELLINGS))
def test_a5_odd_spelling_of_a_plane_target_is_0(tmp_path, capsys, case):
    repo = base_repo(tmp_path)

    def base(r):
        write(r, ".agents/skills/x/SKILL.md", "# x\n")
        symlink(r, ".claude/skills", A5_SPELLINGS[case])

    rebase_main(repo, base)
    pr_source(repo)
    code, out = run_floor(repo, capsys)
    assert code == 0, (case, out)


def test_a6_dangling_plane_link_is_0(tmp_path, capsys):
    repo = base_repo(tmp_path)
    rebase_main(repo, lambda r: symlink(r, ".claude/hooks", "../cfg"))
    pr_source(repo)
    code, out = run_floor(repo, capsys)
    assert code == 0, out


def test_a6_target_absent_at_base_and_ordinary_at_head_is_2(tmp_path, capsys):
    repo = base_repo(tmp_path)
    rebase_main(repo, lambda r: symlink(r, ".claude/hooks", "../cfg"))
    write(repo, "cfg/guard.sh", "#!/bin/sh\nexit 0\n")
    commit(repo, "pr: fill the dangling target off the plane")
    out = undecided(repo, capsys, ".claude/hooks")
    assert "opens cfg, which is not control plane" in out, out
