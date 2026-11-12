"""Regression tests for the first adversarial review of `chock check --floor` (workflow, waivers, scripts, refs).

Each test is one attack, or one correct pull request, asserting the exit code W2-A1v2 owes. Every workflow
edit is a control-plane change: refused under `refuse`, listed with exit 0 under `listed`, never read.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from floor_support import (
    CLAUDE,
    FLOOR_TOKEN,
    INDEX_PIN,
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

SRC = Path(__file__).resolve().parents[1] / "src"
STEP = "      - name: Floor\n"
SHADOW = (
    "      - name: Setup\n        run: mkdir -p b && printf '#!/bin/sh\\nexit 0\\n' > b/chock && chmod +x b/chock"
    ' && echo "$PWD/b" >> "$GITHUB_PATH"\n'
)
HEAD_SHA = "${{ github.event.pull_request.head.sha }}"
WORKFLOW_EDITS = {
    "ci-if-false": (STEP, STEP + "        if: false\n"),
    "ci-continue-on-error": (STEP, STEP + "        continue-on-error: true\n"),
    "ci-job-if-false": ("    runs-on: ubuntu-latest\n", "    if: false\n    runs-on: ubuntu-latest\n"),
    "ci-trigger-narrowed": ("  pull_request_target:\n", "  pull_request_target:\n    branches: [no-such-branch]\n"),
    "ci-env-swap": (STEP, STEP + f"        env:\n          BASE_SHA: {HEAD_SHA}\n"),
    "ci-checkout-with": (STEP, f"        with:\n          ref: {HEAD_SHA}\n" + STEP),
    "ci-shadow-step": (STEP, SHADOW + STEP),
    "fp-step-renamed": ("name: Floor", "name: Chock floor"),
    "fp-trigger-dropped": ("  merge_group:\n", ""),
}


# ---------------- workflows are control plane (V2: no structural reading) ----------------

FLOOR_WORKFLOW = ".github/workflows/chock.yml"


def _workflow(text: str, rel: str = FLOOR_WORKFLOW):
    def change(repo):
        write(repo, rel, text)
        commit(repo, "pr")

    return change


@pytest.mark.parametrize("name", sorted(WORKFLOW_EDITS))
def test_any_edit_to_the_floor_workflow_is_a_control_plane_change(tmp_path, capsys, name):
    old, new = WORKFLOW_EDITS[name]
    control_plane_change(tmp_path, capsys, _workflow(WORKFLOW.replace(old, new, 1)), FLOOR_WORKFLOW)


def test_an_action_bump_in_the_floor_workflow_is_a_control_plane_change(tmp_path, capsys):
    """By design under `refuse`: a Dependabot bump needs a privileged merge, or the base sets `listed`."""

    def change(repo):
        git(repo, "checkout", "-q", "main")
        write(repo, FLOOR_WORKFLOW, WORKFLOW.replace(STEP, "      - uses: actions/setup-python@v5\n" + STEP))
        commit(repo, "base uses setup-python v5")
        git(repo, "checkout", "-q", "-B", "pr")
        write(repo, FLOOR_WORKFLOW, WORKFLOW.replace(STEP, "      - uses: actions/setup-python@v6\n" + STEP))
        commit(repo, "bump setup-python to v6")

    control_plane_change(tmp_path, capsys, change, FLOOR_WORKFLOW)


def test_an_added_workflow_is_a_control_plane_change(tmp_path, capsys):
    """A workflow the head adds can report a check under the floor's name (F3: in the default list)."""
    rel = ".github/workflows/lint.yml"
    control_plane_change(tmp_path, capsys, _workflow("on: push\njobs: {}\n", rel), rel)


# ---------------- first adoption, stale branches, correct pull requests ----------------


def test_base_without_chock_says_nothing_was_judged(tmp_path, capsys):
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    write(repo, "src/app.py", "VALUE = 1\n")
    commit(repo, "base")
    git(repo, "checkout", "-q", "-b", "pr")
    write(repo, "src/config.txt", "key = FLOOR-TOKEN-4242\n")
    write(repo, ".claude/settings.json", CLAUDE)
    commit(repo, "pr")
    code, out = run_floor(repo, capsys)
    assert code == 0, out
    assert "floor: base has no chock gates; nothing was judged" in out


def _stale_branch(repo: Path) -> None:
    write(repo, "src/app.py", "VALUE = 2\n")
    commit(repo, "pr: unrelated edit")
    git(repo, "checkout", "-q", "main")
    doc = json.loads(json.dumps(CLAUDE))
    doc["hooks"]["Stop"] = [{"hooks": [{"type": "command", "command": "sh .chock/bin/launch.sh claude.py --stop"}]}]
    write(repo, ".claude/settings.json", doc)
    gate(repo, "late-policy", {**FLOOR_TOKEN, "params": {"content_pattern": "LATE-[0-9]+"}})
    commit(repo, "main adds a hook and a gate after the pr forked")
    git(repo, "checkout", "-q", "pr")


def test_a_stale_branch_is_undecided_and_its_merge_result_passes(tmp_path, capsys):
    """V1: the floor judges what will land; a branch behind its base is not that, its merge result is."""
    repo = base_repo(tmp_path)
    _stale_branch(repo)
    code, out = run_floor(repo, capsys)
    assert code == 2, out
    assert "is not an ancestor of head" in out
    assert "refs/pull/<n>/merge" in out
    git(repo, "checkout", "-q", "--detach", "main")
    git(repo, "-c", "user.name=t", "-c", "user.email=t@e", "merge", "-q", "--no-ff", "--no-edit", "pr")
    code, out = run_floor(repo, capsys)
    assert code == 0, out
    assert "control-plane" not in out


def test_ok_add_policy_hook_lock_unrelated(tmp_path, capsys):
    """The review's correct pull request: a policy upgrade and a regeneration. By design: refused under
    `refuse` (a privileged merge), listed under `listed`."""
    lock = {
        "lockfile_version": "2",
        "engine": ">=1.3,<2",
        "packs": [{"id": "test-integrity", "version": "1.4.0"}, {"id": "floor-token"}],
    }

    def change(repo):
        gate(repo, "new-policy", {**FLOOR_TOKEN, "params": {"content_pattern": "NEVER-[0-9]+"}})
        doc = json.loads(json.dumps(CLAUDE))
        doc["hooks"]["PreToolUse"][1]["matcher"] = "Edit|Write|MultiEdit"
        command = doc["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
        doc["hooks"]["PreToolUse"][0]["hooks"][0]["command"] = command.replace(INDEX_PIN, "9" * 64)
        write(repo, ".claude/settings.json", doc)
        write(repo, "chock.lock", lock)
        write(repo, "src/app.py", "VALUE = 3\n")
        write(repo, "tests/test_core.py", TEST_FILE + "\ndef test_b():\n    assert True\n")
        commit(repo, "pr")

    control_plane_change(
        tmp_path,
        capsys,
        change,
        ".chock/compiled/new-policy/ci-gate/gate.json",
        ".chock/compiled/new-policy/git-hook/gate.json",
        ".claude/settings.json",
        "chock.lock",
    )


def test_ok_ordinary_pull_request_passes(tmp_path, capsys):
    repo = base_repo(tmp_path)
    write(repo, "src/app.py", "VALUE = 3\n")
    write(repo, "tests/test_core.py", TEST_FILE + "\ndef test_b():\n    assert True\n")
    write(repo, "docs/guide.md", "# Guide\n")
    commit(repo, "pr")
    code, out = run_floor(repo, capsys)
    assert code == 0, out
    assert "control-plane" not in out


# ---------------- waivers (ruling 5) ----------------


def _base_pragma_then(repo: Path, head_text: str) -> None:
    git(repo, "checkout", "-q", "main")
    write(
        repo,
        "tests/test_core.py",
        f"def test_a():\n    # {TEST_PRAGMA}\n    assert 1 + 1 == 2\n    assert 2 * 2 == 4\n",
    )
    commit(repo, "base: an old reviewed removal left its pragma comment")
    git(repo, "checkout", "-q", "-B", "pr")
    write(repo, "tests/test_core.py", head_text)
    commit(repo, "pr")


def test_duplicating_a_base_waiver_line_does_not_waive(tmp_path, capsys):
    repo = base_repo(tmp_path)
    _base_pragma_then(repo, f"def test_a():\n    # {TEST_PRAGMA}\n    # {TEST_PRAGMA}\n    pass\n")
    code, out = run_floor(repo, capsys)
    assert code == 1, out


def test_control_same_without_duplicate_refused(tmp_path, capsys):
    repo = base_repo(tmp_path)
    _base_pragma_then(repo, f"def test_a():\n    # {TEST_PRAGMA}\n    pass\n")
    code, out = run_floor(repo, capsys)
    assert code == 1, out


def test_a_content_waiver_copied_from_the_base_does_not_waive_an_added_line(tmp_path, capsys):
    repo = base_repo(tmp_path)
    git(repo, "checkout", "-q", "main")
    gate(repo, "floor-token", {**FLOOR_TOKEN, "params": {**FLOOR_TOKEN["params"], "allowlist_pragma": "floor-ok"}})
    write(repo, "src/fixture.py", "X = 'FLOOR-TOKEN-1'  # floor-ok\n")
    commit(repo, "base: a reviewed fixture")
    git(repo, "checkout", "-q", "-B", "pr")
    write(repo, "src/fixture.py", "X = 'FLOOR-TOKEN-1'  # floor-ok\nY = 2\nX = 'FLOOR-TOKEN-1'  # floor-ok\n")
    commit(repo, "pr adds a copy of the waived line")
    code, out = run_floor(repo, capsys)
    assert code == 1, out


# ---------------- script gates and rollout (ruling 6) ----------------


def _crashing_probe(repo: Path, *, observe: bool) -> None:
    git(repo, "checkout", "-q", "main")
    write(repo, ".agents/policies/probe/implementations/probe.py", "raise RuntimeError('boom')\n")
    if observe:
        write(repo, ".chock/config.yaml", "rollout: observe\n")
    commit(repo, "base: the script gate crashes")
    git(repo, "checkout", "-q", "-B", "pr")
    write(repo, "src/app.py", "VALUE = 2\n")
    commit(repo, "pr")


@pytest.mark.parametrize("observe", [False, True])
def test_a_crashing_base_script_gate_is_undecided_whatever_the_rollout(tmp_path, capsys, observe):
    repo = base_repo(tmp_path)
    _crashing_probe(repo, observe=observe)
    code, out = run_floor(repo, capsys)
    assert code == 2, out
    assert "UNDECIDED probe [base]: script gate: probe.py crashed" in out


def test_a_content_waiver_on_an_unchanged_line_still_counts(tmp_path, capsys):
    repo = base_repo(tmp_path)
    git(repo, "checkout", "-q", "main")
    gate(repo, "floor-token", {**FLOOR_TOKEN, "params": {**FLOOR_TOKEN["params"], "allowlist_pragma": "floor-ok"}})
    write(repo, "src/fixture.py", "X = 'FLOOR-TOKEN-1'  # floor-ok\n")
    commit(repo, "base: a reviewed fixture")
    git(repo, "checkout", "-q", "-B", "pr")
    write(repo, "src/fixture.py", "X = 'FLOOR-TOKEN-1'  # floor-ok\nY = 2\n")
    commit(repo, "pr edits around it")
    code, out = run_floor(repo, capsys)
    assert code == 0, out


def test_head_cannot_lower_rollout(tmp_path, capsys):
    repo = base_repo(tmp_path)
    write(repo, ".chock/config.yaml", "rollout: observe\n")
    write(repo, "src/config.txt", "key = FLOOR-TOKEN-4242\n")
    commit(repo, "pr")
    code, out = run_floor(repo, capsys)
    assert code == 1, out


def test_a_gate_naming_a_file_outside_the_repository_is_undecided(tmp_path, capsys):
    repo = base_repo(tmp_path)
    git(repo, "checkout", "-q", "main")
    spec = {
        "kind": "dependency_allowlist",
        "on": ["commit"],
        "action": "block",
        "params": {"allowlist_file": "/etc/hostname"},
    }
    gate(repo, "deps", spec, surfaces=("ci-gate",))
    commit(repo, "base: a dependency gate with an absolute allowlist")
    git(repo, "checkout", "-q", "-B", "pr")
    write(repo, "src/app.py", "VALUE = 2\n")
    commit(repo, "pr")
    code, out = run_floor(repo, capsys)
    assert code == 2, out
    assert "not a path inside the repository" in out


# ---------------- refs ----------------


def test_head_not_descendant_of_base_is_undecided(tmp_path, capsys):
    repo = base_repo(tmp_path)
    git(repo, "checkout", "-q", "main")
    write(repo, "src/app.py", "VALUE = 9\n")
    commit(repo, "main moves on")
    git(repo, "checkout", "-q", "pr")
    code, out = run_floor(repo, capsys, "--head", "pr")
    assert code == 2, out
    assert "is not an ancestor of head" in out


def _cli(repo: Path, *args: str) -> int:
    env = {"PATH": os.environ.get("PATH", ""), "PYTHONPATH": str(SRC), "HOME": str(repo.parent)}
    code = "import sys; from chock.lifecycle import check_main; sys.exit(check_main(sys.argv[1:]))"
    proc = subprocess.run(
        [sys.executable, "-c", code, "--repo", str(repo), *args], capture_output=True, text=True, env=env, check=False
    )
    return proc.returncode


def test_ref_arguments(tmp_path):
    repo = base_repo(tmp_path)
    write(repo, "src/config.txt", "key = FLOOR-TOKEN-4242\n")
    commit(repo, "pr")
    assert _cli(repo, "--floor", "--base", "main", "--head", "pr") == 1
    assert _cli(repo, "--floor", "--base", "no-such-ref", "--head", "pr") == 2
    assert _cli(repo, "--floor", "--base=--all", "--head", "pr") == 2
    assert _cli(repo, "--floor", "--base=--since=2000-01-01", "--head", "pr") == 2
    assert _cli(repo, "--floor", "--base", "main", f"--head=--output={tmp_path / 'x'}") == 2
    assert _cli(repo, "--floor", "--base", "pr", "--head", "pr") == 0
