"""Rulings S1-S6 of the floor's fourth pass (W2-A1v2.2), beyond the ported proofs. Each asserts the owed exit."""

from __future__ import annotations

import json
import os
import subprocess

import pytest
from floor_support import CLAUDE, TEST_FILE, base_repo, commit, git, run_floor, write
from floor_support4 import FAKE_A, HOOKLESS, gitlink, raw_commit, rebase_main, rm, symlink, undecided

from chock.validation import checks_floor, floor_git

LISTED = "floor/control-plane-changed (refuse)"


def _base_link(repo, path, target, *files):
    def change(r):
        if path == ".claude":
            rm(r, ".claude")
        for rel in files:
            write(r, rel, CLAUDE)
        symlink(r, path, target)

    rebase_main(repo, change)


@pytest.mark.parametrize(
    ("link", "target", "why"),
    [
        (".claude", ".claude", "more than 32 links"),
        (".claude", "/etc/claude", "absolute or empty target"),
        (".claude", "../../outside", "leaves the repository"),
        (".claude/hooks", "../x/../../up", "leaves the repository"),
    ],
)
def test_a_control_plane_link_that_cannot_resolve_is_undecided(tmp_path, capsys, link, target, why):
    """S1: a loop, an absolute target or a target outside the repository is a failure to resolve."""
    repo = base_repo(tmp_path)
    _base_link(repo, link, target)
    write(repo, "src/app.py", "VALUE = 2\n")
    commit(repo, "pr: an ordinary change")
    out = undecided(repo, capsys, link)
    assert why in out, out


def test_a_link_to_another_control_plane_folder_carries_on(tmp_path, capsys):
    """S1: `.claude -> .codex` stays on the control plane; an ordinary change passes, an edit there is listed."""
    repo = base_repo(tmp_path)
    _base_link(repo, ".claude", ".codex", ".codex/settings.json")
    write(repo, "src/app.py", "VALUE = 2\n")
    commit(repo, "pr")
    code, out = run_floor(repo, capsys)
    assert code == 0, out
    write(repo, ".codex/settings.json", HOOKLESS)
    commit(repo, "pr: through the link")
    code, out = run_floor(repo, capsys)
    assert code == 1, out
    assert "\n  .codex/settings.json\n" in out, out


def test_a_dangling_control_plane_link_carries_on_until_the_head_fills_it(tmp_path, capsys):
    """S1: a link to nothing is fine; once the head creates its target off the plane, it is undecided."""
    repo = base_repo(tmp_path)
    _base_link(repo, ".gemini", "cfg")
    write(repo, "src/app.py", "VALUE = 2\n")
    commit(repo, "pr")
    assert run_floor(repo, capsys)[0] == 0
    write(repo, "cfg/settings.json", HOOKLESS)
    commit(repo, "pr: fill the target")
    undecided(repo, capsys, ".gemini")


def test_a_non_control_plane_hop_is_listed_when_retargeted(tmp_path, capsys):
    """`.claude -> cfg`, `cfg -> .codex`: moving `cfg` to `.cursor` changes what `.claude` opens, so `cfg` is listed."""
    repo = base_repo(tmp_path)

    def change(r):
        rm(r, ".claude")
        write(r, ".codex/settings.json", CLAUDE)
        symlink(r, "cfg", ".codex")
        symlink(r, ".claude", "cfg")

    rebase_main(repo, change)
    symlink(repo, "cfg", ".cursor")
    commit(repo, "pr: retarget the middle link")
    code, out = run_floor(repo, capsys)
    assert code == 1, out
    assert "\n  cfg\n" in out, out


def test_a_link_above_a_nested_agent_folder_is_undecided(tmp_path, capsys):
    """S1, ancestor: `pkg -> vendor` with `vendor/.claude/`: the client opens pkg/.claude through `pkg`."""
    repo = base_repo(tmp_path)
    _base_link(repo, "pkg", "vendor", "vendor/.claude/settings.json")
    write(repo, "src/app.py", "VALUE = 2\n")
    commit(repo, "pr")
    undecided(repo, capsys, "pkg")


def test_an_unrelated_link_out_of_the_repository_is_not_judged(tmp_path, capsys):
    """S1 asks only about links at, inside or above the control plane; others owe no refusal."""
    repo = base_repo(tmp_path)
    _base_link(repo, "docs/shared", "/usr/share/doc")
    write(repo, "src/app.py", "VALUE = 2\n")
    commit(repo, "pr")
    code, out = run_floor(repo, capsys)
    assert code == 0, out


def test_a_gitlink_inside_a_control_plane_folder_is_listed(tmp_path, capsys):
    """S1: a submodule at or inside a control-plane folder is named like any other change to it."""
    repo = base_repo(tmp_path)
    gitlink(repo, ".claude/shared", FAKE_A)
    raw_commit(repo, "pr")
    code, out = run_floor(repo, capsys)
    assert code == 1, out
    assert "\n  .claude/shared\n" in out, out


def test_a_guardrail_changed_and_changed_back_is_named(tmp_path, capsys):
    """S2: hooks off in one commit, back on in the next; the tree diff is empty, the path is still named."""
    repo = base_repo(tmp_path)
    write(repo, ".claude/settings.json", HOOKLESS)
    commit(repo, "off")
    write(repo, ".claude/settings.json", CLAUDE)
    commit(repo, "on again")
    code, out = run_floor(repo, capsys)
    assert code == 1, out
    assert "\n  .claude/settings.json  (in a commit of the range only" in out, out


def test_a_pull_request_merge_of_a_behind_branch_names_nothing_from_the_base(tmp_path, capsys):
    """S2 reads states the base does not have: main's own workflow change, merged into the PR ref, is not the PR's."""
    repo = base_repo(tmp_path)
    write(repo, "src/app.py", "VALUE = 2\n")
    commit(repo, "pr: ordinary")
    git(repo, "checkout", "-q", "main")
    write(repo, ".github/workflows/chock.yml", "name: changed on main\n")
    commit(repo, "main: workflow")
    git(repo, "checkout", "-q", "-b", "merge-ref")
    git(repo, "-c", "user.name=t", "-c", "user.email=t@e", "merge", "-q", "--no-edit", "pr")
    code, out = run_floor(repo, capsys, "--head", "merge-ref")
    assert code == 0, out


def test_attributes_come_from_the_base(tmp_path, capsys):
    """S3: a head `.gitattributes` marking tests binary neither hides a removed assertion nor is itself listed."""
    repo = base_repo(tmp_path)
    write(repo, ".gitattributes", "tests/** binary -diff -text\n")
    write(repo, "tests/test_core.py", TEST_FILE.replace("    assert", "    pass  #"))
    commit(repo, "pr")
    code, out = run_floor(repo, capsys)
    assert code == 1, out
    assert "\n  .gitattributes\n" not in out, out
    assert "GIT_ATTR_SOURCE" not in os.environ


def test_a_git_that_ignores_attr_source_is_undecided(tmp_path, capsys, monkeypatch):
    """S3: a git too old to read attributes from the base is exit 2, naming the version needed."""
    repo = base_repo(tmp_path)
    real = floor_git.git

    def old_git(repo_, *args, data=None):
        if "check-attr" in args:
            return subprocess.CompletedProcess(args, 0, b"", b"")
        return real(repo_, *args, data=data)

    monkeypatch.setattr(floor_git, "git", old_git)
    code, out = run_floor(repo, capsys)
    assert code == 2, out
    assert "git 2.42 or newer" in out, out


def test_first_adoption_writes_a_clean_sarif(tmp_path, capsys):
    """S6: every run writes the file it was asked for, so a stale one never stands in for this run."""
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    write(repo, "src/app.py", "VALUE = 1\n")
    commit(repo, "base")
    sarif = tmp_path / "o.sarif"
    sarif.write_text('{"stale": true}\n')
    code = checks_floor.main(["--repo", str(repo), "--base", "main", "--sarif", str(sarif)])
    assert code == 0, capsys.readouterr()
    doc = json.loads(sarif.read_text())
    assert doc["runs"][0]["invocations"][0]["executionSuccessful"] is True, doc
    assert doc["runs"][0]["results"] == [], doc


def test_an_undecided_link_writes_an_undecided_sarif(tmp_path, capsys):
    """S6: text and SARIF agree on an undecided run."""
    repo = base_repo(tmp_path)
    _base_link(repo, ".claude", "cfg/claude", "cfg/claude/settings.json")
    sarif = tmp_path / "o.sarif"
    code = checks_floor.main(["--repo", str(repo), "--base", "main", "--sarif", str(sarif)])
    assert code == 2, capsys.readouterr()
    invocation = json.loads(sarif.read_text())["runs"][0]["invocations"][0]
    assert invocation["executionSuccessful"] is False
    assert "symbolic link .claude" in invocation["toolExecutionNotifications"][0]["message"]["text"]
