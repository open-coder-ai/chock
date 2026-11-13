"""Regression tests for the second adversarial review of `chock check --floor` (W2-A1r, every proof ported).

Each asserts the exit W2-A1v2 owes: a control-plane attack exits 1 under `refuse` and 0, with the path
listed, under `listed`. Part 2 (refs, encodings, waivers, history, correct PRs) is test_floor_attacks4.py.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from floor_support import (
    CLAUDE,
    FLOOR_TOKEN,
    LOCK,
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
