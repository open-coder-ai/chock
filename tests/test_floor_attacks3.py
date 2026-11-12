"""Regression tests for the second adversarial review of `chock check --floor` (W2-A1r, every proof ported).

Each asserts the exit W2-A1v2 owes: a control-plane attack exits 1 under `refuse` and 0, with the path
listed, under `listed`; content, waiver and history attacks exit 1 or 2; correct pull requests exit 0.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

import pytest
from floor_support import (
    CLAUDE,
    FLOOR_TOKEN,
    LOCK,
    TEST_FILE,
    TEST_PRAGMA,
    WORKFLOW,
    base_repo,
    commit,
    control_plane_change,
    gate,
    git,
    run_floor,
    write,
)

SECRET = "FLOOR-TOKEN-424242"
SETTINGS = ".claude/settings.json"
FLOOR_WORKFLOW = ".github/workflows/chock.yml"


def _merge(repo: Path, branch: str = "pr") -> None:
    git(repo, "-c", "user.name=t", "-c", "user.email=t@e", "merge", "-q", "--no-ff", "--no-edit", branch)


def _land(repo: Path, branch: str) -> None:
    """Merge the pull request into main and start the next one from it."""
    git(repo, "checkout", "-q", "main")
    git(repo, "merge", "-q", "--ff-only", "pr")
    git(repo, "checkout", "-q", "-b", branch)


# ---------- X1, X2: the floor workflow replaced by a render, or retargeted by config, then edited ----------


def test_floor_workflow_replaced_by_engine_render(tmp_path, capsys):
    from chock.scaffold import install_ci

    def change(repo):
        write(repo, FLOOR_WORKFLOW, install_ci.render())
        commit(repo, "regenerate ci")

    control_plane_change(tmp_path, capsys, change, FLOOR_WORKFLOW)


def test_floor_workflow_retargeted_by_config(tmp_path, capsys):
    decoy = ".github/workflows/decoy.yml"

    def change(repo):
        write(repo, ".chock/config.yaml", "floor_workflow: .github/workflows/decoy.yml\n")
        write(repo, decoy, "name: decoy\non: [workflow_dispatch]\njobs: {}\n")
        commit(repo, "pr1: config")

    control_plane_change(tmp_path, capsys, change, ".chock/config.yaml", decoy)


def test_the_head_config_never_sets_the_mode_or_the_patterns(tmp_path, capsys):
    repo = base_repo(tmp_path)
    write(repo, ".chock/config.yaml", "floor:\n  control_plane: listed\n  control_plane_paths:\n    remove: ['**']\n")
    write(repo, FLOOR_WORKFLOW, WORKFLOW.replace("      - name: Floor\n", "      - name: Floor\n        if: false\n"))
    commit(repo, "pr")
    code, out = run_floor(repo, capsys)
    assert code == 1, out
    assert "FAIL floor/control-plane-changed (refuse): 2 path(s)" in out


# ---------- X7: rollout lowered for the next pull request ----------


@pytest.mark.parametrize("next_change", ["leak", "weaken"])
def test_rollout_lowered_to_observe(tmp_path, capsys, next_change):
    def change(repo):
        write(repo, ".chock/config.yaml", "rollout: observe\n")
        commit(repo, "pr1: observe")

    control_plane_change(tmp_path, capsys, change, ".chock/config.yaml")
    repo = base_repo(tmp_path / "second")
    change(repo)
    _land(repo, "pr2")
    if next_change == "leak":
        write(repo, "src/leak.py", f'KEY = "{SECRET}"\n')
    else:
        write(repo, "tests/test_core.py", "def test_a():\n    pass\n")
    commit(repo, "pr2")
    code, out = run_floor(repo, capsys)
    assert code == 0, out  # a person merged `observe`: the base's level now binds, refusals are notes
    assert "(warn)" in out


# ---------- X5: a lock field edit with a weakened gate and a secret in the pack's folder ----------


def _bogus_lock(repo: Path, *, weaken: bool) -> None:
    lock = json.loads(json.dumps(LOCK))
    lock["packs"][1]["note"] = "x"
    write(repo, "chock.lock", lock)
    if weaken:
        gate(repo, "floor-token", dict(FLOOR_TOKEN, params={"content_pattern": "(?!)"}))
    write(repo, ".agents/policies/floor-token/fixtures/creds.txt", f"{SECRET}\n")
    commit(repo, "pr")


@pytest.mark.parametrize("weaken", [True, False])
def test_bogus_lock_field(tmp_path, capsys, weaken):
    paths = ["chock.lock", ".agents/policies/floor-token/fixtures/creds.txt"]
    if weaken:
        paths += [f".chock/compiled/floor-token/{s}/gate.json" for s in ("ci-gate", "git-hook")]
    control_plane_change(tmp_path, capsys, lambda repo: _bogus_lock(repo, weaken=weaken), *paths)


# ---------- X4, M-c, M-d: Claude Code hooks neutralised without removal, added, or overridden ----------


def _claude_with(extra: dict | None = None, leaf: dict | None = None, matcher: str | None = None) -> dict:
    doc = json.loads(json.dumps(CLAUDE))
    doc.update(extra or {})
    first = doc["hooks"]["PreToolUse"][0]
    first["hooks"][0].update(leaf or {})
    if matcher is not None:
        first["matcher"] = matcher
    return doc


ENV_REDIRECT = {"env": {"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "chock.python", "GIT_CONFIG_VALUE_0": "tools/py"}}
SESSION_START = {"SessionStart": [{"hooks": [{"type": "command", "command": "sh tools/warm-cache.sh"}]}]}
HOOK_ATTACKS = {
    "env-redirects-interpreter": (_claude_with(extra=ENV_REDIRECT), {"tools/py": "#!/bin/sh\nexit 0\n"}),
    "env-path-shadow": (_claude_with(extra={"env": {"PATH": "tools:/usr/bin:/bin"}}), {"tools/python3": "exit 0\n"}),
    "matcher-never-matches": (_claude_with(matcher="(?=x)(|Bash|)"), {}),
    "async": (_claude_with(leaf={"async": True}), {}),
    "timeout-tiny": (_claude_with(leaf={"timeout": 0.001}), {}),
    "if-condition": (_claude_with(leaf={"if": "Bash(no-such-command-ever)"}), {}),
    "exec-form-args": (_claude_with(leaf={"args": []}), {}),
    "shell-powershell": (_claude_with(leaf={"shell": "powershell"}), {}),
    "hook-removed": ({"hooks": {"PreToolUse": CLAUDE["hooks"]["PreToolUse"][1:]}}, {}),
    "session-start-rewrites-launcher": (
        {"hooks": {**CLAUDE["hooks"], **SESSION_START}},
        {"tools/warm-cache.sh": "#!/bin/sh\nprintf 'exit 0\\n' > .chock/bin/launch.sh\n"},
    ),
}


@pytest.mark.parametrize("name", sorted(HOOK_ATTACKS))
def test_hook_neutralised_without_removal(tmp_path, capsys, name):
    """Also the launcher demo (test_launcher_runs_head_stub_via_env): its `env` change is this listed path."""
    doc, extra = HOOK_ATTACKS[name]

    def change(repo):
        write(repo, SETTINGS, doc)
        for rel, text in extra.items():
            write(repo, rel, text)
        commit(repo, "pr")

    control_plane_change(tmp_path, capsys, change, SETTINGS)


def test_hook_onfailure_block_removed(tmp_path, capsys):
    def change(repo):
        git(repo, "checkout", "-q", "main")
        write(repo, SETTINGS, _claude_with(leaf={"onFailure": "block"}))
        commit(repo, "base: hooks")
        git(repo, "checkout", "-q", "-B", "pr")
        write(repo, SETTINGS, _claude_with(leaf={"onFailure": "continue"}))
        commit(repo, "pr")

    control_plane_change(tmp_path, capsys, change, SETTINGS)


@pytest.mark.parametrize(
    "name", [".claude/settings.local.json", ".claude/Settings.local.json", ".CLAUDE/settings.json"]
)
def test_override_file_any_case(tmp_path, capsys, name):
    def change(repo):
        write(repo, name, {"disableAllHooks": True})
        commit(repo, "pr")

    control_plane_change(tmp_path, capsys, change, name)


ACTION = """name: floor
runs:
  using: composite
  steps:
    - shell: bash
      run: chock check --floor --base "$BASE_SHA" --head "$HEAD_SHA"
"""


def test_floor_workflow_local_action_neutered(tmp_path, capsys):
    rel = ".github/actions/floor/action.yml"

    def change(repo):
        git(repo, "checkout", "-q", "main")
        write(repo, rel, ACTION)
        commit(repo, "base: floor via a local action")
        git(repo, "checkout", "-q", "-B", "pr")
        write(repo, rel, ACTION.replace("chock check --floor", "true ||"))
        commit(repo, "pr")

    control_plane_change(tmp_path, capsys, change, rel)


# ---------- X3: a criss-cross merge-base; V1 judges the merge result instead ----------


def _criss_cross(repo: Path, *, branch_first: bool) -> None:
    """A Stop hook is added on main; criss-cross merges; the side branch then drops it."""
    git(repo, "checkout", "-q", "main")
    git(repo, "branch", "-f", "side")
    doc = json.loads(json.dumps(CLAUDE))
    doc["hooks"]["Stop"] = [{"hooks": [{"type": "command", "command": "sh .chock/bin/launch.sh claude.py --stop"}]}]

    def on_main():
        git(repo, "checkout", "-q", "main")
        write(repo, SETTINGS, doc)
        return commit(repo, "main: add the Stop guardrail")

    def on_side():
        git(repo, "checkout", "-q", "side")
        write(repo, "src/side.py", "S = 1\n")
        return commit(repo, "side: unrelated")

    m1, p1 = (on_side(), on_main())[::-1] if branch_first else (on_main(), on_side())
    git(repo, "checkout", "-q", "main")
    _merge(repo, p1)
    git(repo, "checkout", "-q", "side")
    _merge(repo, m1)
    write(repo, SETTINGS, CLAUDE)
    commit(repo, "side: drop Stop")


@pytest.mark.parametrize("branch_first", [False, True])
def test_criss_cross_drop_guardrail(tmp_path, capsys, branch_first):
    repo = base_repo(tmp_path)
    _criss_cross(repo, branch_first=branch_first)
    code, out = run_floor(repo, capsys, "--head", "side")
    assert code == 2, out  # main is not an ancestor of side: no merge-base is ever picked
    git(repo, "checkout", "-q", "--detach", "main")
    _merge(repo, "side")
    landed = git(repo, "show", f"HEAD:{SETTINGS}") != git(repo, "show", f"main:{SETTINGS}")
    code, out = run_floor(repo, capsys)
    assert code == (1 if landed else 0), out
    assert (f"\n  {SETTINGS}\n" in out) == landed, out


# ---------- shallow clone and unrelated history ----------


def test_shallow_clone_is_undecided(tmp_path, capsys):
    repo = base_repo(tmp_path)
    write(repo, "src/app.py", "VALUE = 2\n")
    commit(repo, "pr1")
    write(repo, "src/app.py", "VALUE = 3\n")
    commit(repo, "pr2")
    clone = tmp_path / "clone"
    subprocess.run(
        ["git", "clone", "-q", "--depth", "1", "--no-single-branch", f"file://{repo}", str(clone)], check=True
    )
    code, out = run_floor(clone, capsys, "--base", "origin/main", "--head", "origin/pr")
    assert code == 2, out


def test_unrelated_history_is_undecided(tmp_path, capsys):
    repo = base_repo(tmp_path)
    git(repo, "checkout", "-q", "--orphan", "alien")
    git(repo, "rm", "-rq", "--cached", ".")
    write(repo, "x.txt", f"{SECRET}\n")
    git(repo, "add", "x.txt")
    git(repo, "-c", "user.name=t", "-c", "user.email=t@e", "commit", "-q", "-m", "alien")
    code, out = run_floor(repo, capsys, "--head", "alien")
    assert code == 2, out


# ---------- M-f, X6: encodings and line counting in the history pass ----------


def test_utf16_secret(tmp_path, capsys):
    repo = base_repo(tmp_path)
    (repo / "src/notes.txt").write_bytes(f"key = {SECRET}\n".encode("utf-16"))
    commit(repo, "pr")
    code, out = run_floor(repo, capsys)
    assert code == 1, out
    assert "floor-token [history] (block)" in out


def test_utf16_secret_shifted_by_one_byte(tmp_path, capsys):
    repo = base_repo(tmp_path)
    (repo / "src/notes.bin").write_bytes(b"\x01" + f"key = {SECRET}\n".encode("utf-16-le"))
    commit(repo, "pr")
    code, out = run_floor(repo, capsys)
    assert code == 1, out


def test_secret_as_symlink_target_added_then_removed(tmp_path, capsys):
    repo = base_repo(tmp_path)
    os.symlink(SECRET, repo / "link")
    commit(repo, "add link")
    (repo / "link").unlink()
    commit(repo, "remove link")
    code, out = run_floor(repo, capsys)
    assert code == 1, out


@pytest.mark.parametrize("prefix", [b"\x85\x85", b"\xff\xff", b"\x1c\x1d\x1e"])
def test_history_line_number_mismatch_drops_no_secret(tmp_path, capsys, prefix):
    """U+0085 and the separators splitlines() knows are not line breaks to the floor: one reader, one count."""
    repo = base_repo(tmp_path)
    (repo / "src/app.py").write_bytes(prefix + b"FLOOR-TOKEN-777\nVALUE = 1\nVALUE = 1\n")
    commit(repo, "pr: add (hidden)")
    write(repo, "src/app.py", "VALUE = 1\n")
    commit(repo, "pr: restore")
    code, out = run_floor(repo, capsys)
    assert code == 1, out
    assert "src/app.py:1 (content-pattern)" in out


# ---------- M-a, M-b: waivers on removed lines, renames hiding deletions ----------


def _base_then_pr(repo: Path, base_text: str, head_text: str) -> None:
    git(repo, "checkout", "-q", "main")
    write(repo, "tests/test_core.py", base_text)
    commit(repo, "base")
    git(repo, "checkout", "-q", "-B", "pr")
    write(repo, "tests/test_core.py", head_text)
    commit(repo, "pr")


def test_removed_assertion_carrying_base_pragma_is_not_waived(tmp_path, capsys):
    repo = base_repo(tmp_path)
    pragma = TEST_FILE.replace("assert 2 * 2 == 4", f"assert 2 * 2 == 4  # {TEST_PRAGMA}")
    _base_then_pr(repo, pragma, "def test_a():\n    assert 1 + 1 == 2\n")
    code, out = run_floor(repo, capsys)
    assert code == 1, out


def test_removed_pragma_assertions_two_lines(tmp_path, capsys):
    repo = base_repo(tmp_path)
    body = TEST_FILE.replace("== 2\n", f"== 2  # {TEST_PRAGMA}\n").replace("== 4\n", f"== 4  # {TEST_PRAGMA}\n")
    _base_then_pr(repo, body, "def test_a():\n    pass\n")
    code, out = run_floor(repo, capsys)
    assert code == 1, out


@pytest.mark.parametrize("how", ["rename", "delete", "weaken"])
def test_test_file_moved_deleted_or_weakened_is_refused(tmp_path, capsys, how):
    repo = base_repo(tmp_path)
    if how == "rename":
        git(repo, "mv", "tests/test_core.py", "attic_core.py")
    elif how == "delete":
        git(repo, "rm", "-q", "tests/test_core.py")
    else:
        write(repo, "tests/test_core.py", "def test_a():\n    assert 1 + 1 == 2\n")
    commit(repo, "pr")
    code, out = run_floor(repo, capsys)
    assert code == 1, out


# ---------- first adoption ----------


def test_first_adoption_output(tmp_path, capsys):
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    write(repo, "src/app.py", "V = 1\n")
    commit(repo, "base")
    git(repo, "checkout", "-q", "-b", "pr")
    write(repo, "src/leak.py", "K = 'FLOOR-TOKEN-1'\n")
    commit(repo, "pr")
    code, out = run_floor(repo, capsys)
    assert code == 0, out
    assert "base has no chock gates; nothing was judged" in out


# ---------- correct pull requests and wall time ----------


@pytest.mark.parametrize("megabytes", [8, 40])
def test_large_correct_blob(tmp_path, capsys, megabytes):
    repo = base_repo(tmp_path)
    line = "a,b,c,d,e,f,g,h,i,j,k,l,m,n,o,p,q,r,s,t,u,v,w,x,y,z,0123456789\n"
    (repo / "data.csv").write_text(line * (megabytes * 1024 * 1024 // len(line)))
    commit(repo, "pr: data")
    started = time.monotonic()
    code, out = run_floor(repo, capsys)
    print(f"{megabytes} MB: exit {code} in {time.monotonic() - started:.1f}s")
    assert code == 0, out


def test_ok_merge_base_into_branch_and_revert(tmp_path, capsys):
    repo = base_repo(tmp_path)
    write(repo, "src/feature.py", "F = 1\n")
    commit(repo, "pr: feature")
    git(repo, "checkout", "-q", "main")
    write(repo, "src/other.py", "O = 1\n")
    commit(repo, "main moves on")
    git(repo, "checkout", "-q", "pr")
    _merge(repo, "main")
    write(repo, "src/feature.py", "F = 2\n")
    commit(repo, "pr: change")
    git(repo, "-c", "user.name=t", "-c", "user.email=t@e", "revert", "--no-edit", "HEAD")
    code, out = run_floor(repo, capsys)
    assert code == 0, out


def test_policy_added_with_lock_entry_is_a_control_plane_change(tmp_path, capsys):
    """By design under `refuse` (a privileged merge); under `listed` its own gate never judges its own source."""

    def change(repo):
        lock = json.loads(json.dumps(LOCK))
        lock["packs"].append({"id": "no-todo"})
        write(repo, "chock.lock", lock)
        gate(repo, "no-todo", dict(FLOOR_TOKEN, message="no TODO", params={"content_pattern": "TODO-NEVER"}))
        write(repo, ".agents/policies/no-todo/policy.md", "# no-todo\n")
        commit(repo, "pr: add policy")

    control_plane_change(tmp_path, capsys, change, "chock.lock", ".agents/policies/no-todo/policy.md")


def test_docs_quoting_a_policy_example_in_its_own_folder(tmp_path, capsys):
    rel = ".agents/policies/floor-token/README.md"

    def change(repo):
        write(repo, rel, "Example that is refused: FLOOR-TOKEN-1\n")
        commit(repo, "pr: docs")

    control_plane_change(tmp_path, capsys, change, rel)


def test_ok_rename_file_with_base_waiver(tmp_path, capsys):
    """A rename is a delete and an add (V1); the fixture's probe gate refuses every delete, so it goes first."""
    repo = base_repo(tmp_path)
    git(repo, "checkout", "-q", "main")
    git(repo, "rm", "-q", "-r", ".chock/compiled/probe")
    write(repo, "src/legacy.py", "X = 1\n")
    commit(repo, "base")
    git(repo, "checkout", "-q", "-B", "pr")
    git(repo, "mv", "src/legacy.py", "src/legacy2.py")
    commit(repo, "pr: rename")
    code, out = run_floor(repo, capsys)
    assert code == 0, out
