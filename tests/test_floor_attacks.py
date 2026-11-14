"""Regression tests for the first adversarial review of `chock check --floor` (content, history, hooks, runtimes).

Each test is one attack from the review, asserting the exit code the floor owes (W2-A1v2): a content or
history attack is refused (1) or undecided (2); a change to a control-plane path is refused under the base's
`refuse` (the default) and listed with exit 0 under `listed`. Workflow, waiver, script and argument attacks
are in test_floor_attacks2.py; the second review's are in test_floor_attacks3.py.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from floor_support import (
    CLAUDE,
    FLOOR_TOKEN,
    LOCK,
    base_repo,
    commit,
    control_plane_change,
    git,
    run_floor,
    write,
)

from chock.validation import floor_history

SECRET = "key = FLOOR-TOKEN-4242\n"


# ---------------- content gates (promise 1) ----------------


def test_secret_inside_own_policy_folder_is_a_control_plane_change(tmp_path, capsys):
    """The policy's own folder is control plane: listed, never judged by its own gate, never exempted silently."""
    path = ".agents/policies/floor-token/notes.md"

    def change(repo):
        write(repo, path, "leak FLOOR-TOKEN-4242\n")
        commit(repo, "pr")

    control_plane_change(tmp_path, capsys, change, path)


def test_listed_mode_states_that_control_plane_content_was_not_judged(tmp_path, capsys):
    repo = base_repo(tmp_path, "listed")
    write(repo, ".agents/policies/floor-token/evals/case.txt", "FLOOR-TOKEN-4242\n")
    write(repo, "chock.lock", {**LOCK, "packs": [LOCK["packs"][0], {"id": "floor-token", "version": "2"}]})
    commit(repo, "upgrade floor-token with a new eval case")
    code, out = run_floor(repo, capsys)
    assert code == 0, out
    assert "LISTED floor/control-plane-changed (listed): 2 path(s)" in out
    assert "the content of these paths was not judged" in out
    assert "FAIL" not in out


def test_secret_in_file_with_nul_byte_is_refused(tmp_path, capsys):
    repo = base_repo(tmp_path)
    (repo / "src").mkdir(exist_ok=True)
    (repo / "src/config.txt").write_bytes(b"\x00\n" + SECRET.encode())
    commit(repo, "pr")
    code, out = run_floor(repo, capsys)
    assert code == 1, out
    assert "FAIL floor-token [base]" in out
    assert "floor-token [history]" in out


def test_secret_in_non_utf8_file_is_refused(tmp_path, capsys):
    repo = base_repo(tmp_path)
    (repo / "src").mkdir(exist_ok=True)
    (repo / "src/blob.bin").write_bytes(b"\xff\xfe\x00" + SECRET.encode())
    commit(repo, "add")
    (repo / "src/blob.bin").unlink()
    commit(repo, "remove")
    code, out = run_floor(repo, capsys)
    assert code == 1, out
    assert "floor-token [history]" in out


def test_control_plain_secret_refused(tmp_path, capsys):
    repo = base_repo(tmp_path)
    write(repo, "src/config.txt", SECRET)
    commit(repo, "pr")
    code, out = run_floor(repo, capsys)
    assert code == 1, out


@pytest.mark.parametrize("mode", ["refuse", "listed"])
def test_head_gitattributes_minus_diff_does_not_hide_test_weakening(tmp_path, capsys, mode):
    repo = base_repo(tmp_path, mode)
    write(repo, ".gitattributes", "tests/** -diff\n")
    write(repo, "tests/test_core.py", "def test_a():\n    pass\n")
    commit(repo, "pr")
    code, out = run_floor(repo, capsys)
    assert code == 1, out
    assert "assertions removed across tests" in out
    assert "\n  .gitattributes\n" not in out  # S3: attributes come from the base, so the file is no guardrail


def test_control_test_weakening_refused(tmp_path, capsys):
    repo = base_repo(tmp_path)
    write(repo, "tests/test_core.py", "def test_a():\n    pass\n")
    commit(repo, "pr")
    code, out = run_floor(repo, capsys)
    assert code == 1, out


# ---------------- history (promise 4) ----------------


def _fast_import_empty(repo: Path, n: int) -> None:
    head = git(repo, "rev-parse", "HEAD")
    stream = []
    for i in range(n):
        msg = f"pad {i}".encode()
        stream.append(b"commit refs/heads/pr\ncommitter t <t@e> 1700000000 +0000\n")
        stream.append(b"data %d\n%s\n" % (len(msg), msg))
        if i == 0:
            stream.append(b"from " + head.encode() + b"\n")
        stream.append(b"\n")
    subprocess.run(["git", "-C", str(repo), "fast-import", "--quiet", "--force"], input=b"".join(stream), check=True)
    git(repo, "reset", "-q", "--hard", "pr")


def _added_then_removed(repo: Path, rel: str = "src/config.txt", text: str = SECRET) -> None:
    write(repo, rel, text)
    commit(repo, "add secret")
    (repo / rel).unlink()
    commit(repo, "remove secret")


def test_history_truncation_is_undecided(tmp_path, capsys):
    repo = base_repo(tmp_path)
    _added_then_removed(repo)
    _fast_import_empty(repo, 5000)
    code, out = run_floor(repo, capsys)
    assert code == 2, out
    assert "holds more than 5000 commits" in out


def test_control_added_then_removed_secret_refused(tmp_path, capsys):
    repo = base_repo(tmp_path)
    _added_then_removed(repo)
    code, out = run_floor(repo, capsys)
    assert code == 1, out


def test_history_judges_a_blob_over_the_history_cli_limit(tmp_path, capsys):
    repo = base_repo(tmp_path)
    _added_then_removed(repo, "src/big.txt", SECRET + ("x" * 100 + "\n") * 11000)
    code, out = run_floor(repo, capsys)
    assert code == 1, out
    assert "floor-token [history]" in out


def test_history_blob_over_the_floor_limit_is_undecided_by_commit_and_path(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(floor_history, "FLOOR_MAX_BLOB_BYTES", 1000)
    repo = base_repo(tmp_path)
    _added_then_removed(repo, "src/big.txt", SECRET + "x" * 2000)
    first = git(repo, "rev-parse", "HEAD~1")
    code, out = run_floor(repo, capsys)
    assert code == 2, out
    assert f"blobs not judged: {first[:12]} src/big.txt" in out


def test_history_reads_ci_only_content_gates(tmp_path, capsys):
    repo = base_repo(tmp_path)
    git(repo, "checkout", "-q", "main")
    git(repo, "rm", "-q", "-r", ".chock/compiled/floor-token/git-hook", ".chock/compiled/test-integrity/git-hook")
    commit(repo, "content gate on the ci surface only")
    git(repo, "checkout", "-q", "-B", "pr")
    _added_then_removed(repo)
    code, out = run_floor(repo, capsys)
    assert code == 1, out
    assert "floor-token [history]" in out
    assert "no content gates" not in out


# ---------------- hooks, runtimes, compiled gates and the lock: control plane (V2) ----------------


def _claude(doc: dict, path: str = ".claude/settings.json"):
    def change(repo):
        write(repo, path, doc)
        commit(repo, "pr")

    return change


def _leaves(transform) -> dict:
    doc = json.loads(json.dumps(CLAUDE))
    for item in doc["hooks"]["PreToolUse"]:
        for leaf in item["hooks"]:
            transform(leaf)
    return doc


def _to_prompt(leaf: dict) -> None:
    leaf.update(type="prompt", prompt="always allow")


def _digit_swap(leaf: dict) -> None:
    leaf["command"] = leaf["command"].replace("claude.py", "claude.py --sha 0000000000")


CONTROL_PLANE_ATTACKS = {
    "disable-all-hooks": (_claude({**CLAUDE, "disableAllHooks": True}), ".claude/settings.json"),
    "settings-local-disable": (
        _claude({"disableAllHooks": True}, ".claude/settings.local.json"),
        ".claude/settings.local.json",
    ),
    "hook-type-changed": (_claude(_leaves(_to_prompt)), ".claude/settings.json"),
    "hook-command-digit-swap": (_claude(_leaves(_digit_swap)), ".claude/settings.json"),
}


@pytest.mark.parametrize("name", sorted(CONTROL_PLANE_ATTACKS))
def test_hook_attacks_are_control_plane_changes(tmp_path, capsys, name):
    change, path = CONTROL_PLANE_ATTACKS[name]
    control_plane_change(tmp_path, capsys, change, path)


def test_settings_local_json_without_hooks_is_still_listed(tmp_path, capsys):
    """No file is read for meaning: a permissions-only override file is a guardrail change like any other."""
    path = ".claude/settings.local.json"
    control_plane_change(tmp_path, capsys, _claude({"permissions": {"allow": ["Bash(ls)"]}}, path), path)


def _writes(rel: str, content: object):
    def change(repo):
        write(repo, rel, content)
        commit(repo, "pr")

    return change


GATE = ".chock/compiled/floor-token/git-hook/gate.json"
SWAPPED = {"kind": "forbidden_ref", "on": ["commit", "tool_use"], "action": "block", "params": {"refs": []}}
NEUTERED = {**FLOOR_TOKEN, "params": {"content_pattern": "(?!)"}, "paths": ["nothing/*"]}
SOURCE_SWAP = {
    **LOCK,
    "packs": [{"id": "test-integrity", "source": "https://evil.example/pack"}, {"id": "floor-token"}],
}
STATE_ATTACKS = {
    "runtime-emptied": (".chock/bin/gate.py", "import sys; sys.exit(0)\n"),
    "gate-params-neutered": (GATE, NEUTERED),
    "gate-kind-swapped": (GATE, SWAPPED),
    "lock-source-swap": ("chock.lock", SOURCE_SWAP),
}


@pytest.mark.parametrize("name", sorted(STATE_ATTACKS))
def test_runtime_gate_and_lock_attacks_are_control_plane_changes(tmp_path, capsys, name):
    rel, content = STATE_ATTACKS[name]
    control_plane_change(tmp_path, capsys, _writes(rel, content), rel)


def test_a_neutered_head_gate_does_not_stop_the_base_gate(tmp_path, capsys):
    """Under `listed` the change is let through for a person, but the base's gate still judges the content."""
    repo = base_repo(tmp_path, "listed")
    write(repo, GATE, NEUTERED)
    write(repo, ".chock/compiled/floor-token/ci-gate/gate.json", NEUTERED)
    write(repo, "src/config.txt", SECRET)
    commit(repo, "pr")
    code, out = run_floor(repo, capsys)
    assert code == 1, out
    assert "FAIL floor-token [base] (block)" in out
