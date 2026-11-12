"""Regression tests for the adversarial review of `chock check --floor` (content, history, hooks, runtimes).

Each test is one attack from the review, asserting the exit code the floor owes: 1 refused, 2 undecided,
0 for a correct pull request. Workflow, waiver, script and argument attacks are in test_floor_attacks2.py.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from floor_support import CLAUDE, FLOOR_TOKEN, LOCK, base_repo, commit, git, run_floor, write

from chock.validation import floor_history

SECRET = "key = FLOOR-TOKEN-4242\n"


# ---------------- content gates (promise 1) ----------------


def test_secret_inside_own_policy_folder_is_refused(tmp_path, capsys):
    repo = base_repo(tmp_path)
    write(repo, ".agents/policies/floor-token/notes.md", "leak FLOOR-TOKEN-4242\n")
    commit(repo, "pr")
    code, out = run_floor(repo, capsys)
    assert code == 1, out
    assert "FAIL floor-token [base]" in out
    assert (
        "floor/pack-changed: floor-token: no lock change, so every gate judged it; "
        "source: .agents/policies/floor-token/notes.md" in out
    )


def test_own_folder_is_exempt_only_with_a_lock_change_and_is_listed(tmp_path, capsys):
    repo = base_repo(tmp_path)
    write(repo, ".agents/policies/floor-token/evals/case.txt", "FLOOR-TOKEN-4242\n")
    write(repo, "chock.lock", {**LOCK, "packs": [LOCK["packs"][0], {"id": "floor-token", "version": "2"}]})
    commit(repo, "upgrade floor-token with a new eval case")
    code, out = run_floor(repo, capsys)
    assert code == 0, out
    assert (
        "floor/pack-changed: floor-token: lock entry changed; its own gates do not judge its source: "
        ".agents/policies/floor-token/evals/case.txt" in out
    )


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


def test_head_gitattributes_minus_diff_does_not_hide_test_weakening(tmp_path, capsys):
    repo = base_repo(tmp_path)
    write(repo, ".gitattributes", "tests/** -diff\n")
    write(repo, "tests/test_core.py", "def test_a():\n    pass\n")
    commit(repo, "pr")
    code, out = run_floor(repo, capsys)
    assert code == 1, out
    assert "assertions removed across tests" in out


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


# ---------------- hooks (promise 3, ruling 3) ----------------


def _claude(repo: Path, doc: dict) -> None:
    write(repo, ".claude/settings.json", doc)
    commit(repo, "pr")


def test_disable_all_hooks_key_is_refused(tmp_path, capsys):
    repo = base_repo(tmp_path)
    _claude(repo, {**CLAUDE, "disableAllHooks": True})
    code, out = run_floor(repo, capsys)
    assert code == 1, out
    assert "tamper/hooks-disabled .claude/settings.json: /disableAllHooks turns every hook off" in out


def test_settings_local_json_disable_is_refused(tmp_path, capsys):
    repo = base_repo(tmp_path)
    write(repo, ".claude/settings.local.json", {"disableAllHooks": True})
    commit(repo, "pr")
    code, out = run_floor(repo, capsys)
    assert code == 1, out
    assert "tamper/hooks-overridden .claude/settings.local.json" in out


def test_settings_local_json_without_hooks_passes(tmp_path, capsys):
    repo = base_repo(tmp_path)
    write(repo, ".claude/settings.local.json", {"permissions": {"allow": ["Bash(ls)"]}})
    commit(repo, "pr")
    code, out = run_floor(repo, capsys)
    assert code == 0, out


def test_hook_type_changed_is_refused(tmp_path, capsys):
    repo = base_repo(tmp_path)
    doc = json.loads(json.dumps(CLAUDE))
    for item in doc["hooks"]["PreToolUse"]:
        for leaf in item["hooks"]:
            leaf["type"] = "prompt"
            leaf["prompt"] = "always allow"
    _claude(repo, doc)
    code, out = run_floor(repo, capsys)
    assert code == 1, out
    assert "tamper/hook-removed .claude/settings.json: PreToolUse command hook removed" in out


@pytest.mark.parametrize("run", ["--sha 0000000000", "--budget 1.2.3"])
def test_hook_command_digit_swap_is_refused(tmp_path, capsys, run):
    """Only the index pin is normalised: any other run of digits or hex in a command is part of its identity."""
    repo = base_repo(tmp_path)
    git(repo, "checkout", "-q", "main")
    doc = json.loads(json.dumps(CLAUDE))
    doc["hooks"]["PreToolUse"][1]["hooks"][0]["command"] += " --sha abc1234def --budget 9.9.9"
    _claude(repo, doc)
    git(repo, "checkout", "-q", "-B", "pr")
    flag = run.split()[0]
    words = doc["hooks"]["PreToolUse"][1]["hooks"][0]["command"].split()
    words[words.index(flag) + 1] = run.split()[1]
    doc["hooks"]["PreToolUse"][1]["hooks"][0]["command"] = " ".join(words)
    _claude(repo, doc)
    code, out = run_floor(repo, capsys)
    assert code == 1, out
    assert "tamper/hook-removed .claude/settings.json" in out


def test_vendors_without_verified_switches_are_named_not_covered(tmp_path, capsys):
    repo = base_repo(tmp_path)
    write(repo, "src/other.py", "X = 1\n")
    commit(repo, "pr")
    code, out = run_floor(repo, capsys)
    assert code == 0, out
    assert "note: floor/hook-switches not covered: cursor" in out


# ---------------- runtimes, compiled gates and the lock (rulings 4 and 7) ----------------


def test_runtime_emptied_is_refused(tmp_path, capsys):
    repo = base_repo(tmp_path)
    write(repo, ".chock/bin/gate.py", "import sys; sys.exit(0)\n")
    commit(repo, "pr")
    code, out = run_floor(repo, capsys)
    assert code == 1, out
    assert "tamper/runtime-changed .chock/bin/gate.py" in out


def test_git_hook_gate_params_neutered_is_refused(tmp_path, capsys):
    repo = base_repo(tmp_path)
    neutered = {**FLOOR_TOKEN, "params": {"content_pattern": "(?!)"}, "paths": ["nothing/*"]}
    write(repo, ".chock/compiled/floor-token/git-hook/gate.json", neutered)
    commit(repo, "pr")
    code, out = run_floor(repo, capsys)
    assert code == 1, out
    assert "tamper/gate-changed .chock/compiled/floor-token/git-hook/gate.json" in out


def test_gate_kind_swapped_is_refused(tmp_path, capsys):
    repo = base_repo(tmp_path)
    swapped = {"kind": "forbidden_ref", "on": ["commit", "tool_use"], "action": "block", "params": {"refs": []}}
    write(repo, ".chock/compiled/floor-token/git-hook/gate.json", swapped)
    commit(repo, "pr")
    code, out = run_floor(repo, capsys)
    assert code == 1, out
    assert "tamper/gate-changed .chock/compiled/floor-token/git-hook/gate.json" in out


def test_lock_pack_source_swap_is_listed_by_name(tmp_path, capsys):
    """A lock entry change is the signal a pack changed; the floor names it rather than refusing (ruling 7)."""
    repo = base_repo(tmp_path)
    lock = {**LOCK, "packs": [{"id": "test-integrity", "source": "https://evil.example/pack"}, {"id": "floor-token"}]}
    write(repo, "chock.lock", lock)
    commit(repo, "pr")
    code, out = run_floor(repo, capsys)
    assert code == 0, out
    assert "floor/pack-changed: test-integrity: lock entry changed" in out
