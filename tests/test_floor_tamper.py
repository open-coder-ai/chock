"""`chock check --floor` refuses, by name, a removed or weakened guardrail, and stays silent on a regeneration."""

from __future__ import annotations

import json

from floor_support import CLAUDE, CURSOR, FLOOR_TOKEN, LOCK, WORKFLOW, base_repo, commit, gate, run_floor, write


def test_an_unrelated_change_passes_with_no_tamper_line(tmp_path, capsys) -> None:
    repo = base_repo(tmp_path)
    write(repo, "src/other.py", "OTHER = 2\n")
    commit(repo, "pr")
    code, out = run_floor(repo, capsys)
    assert code == 0, out
    assert "tamper/" not in out
    assert "unverified by chock" in out


def test_deleting_a_vendor_hook_file_is_refused_by_name(tmp_path, capsys) -> None:
    repo = base_repo(tmp_path)
    (repo / ".cursor/hooks.json").unlink()
    commit(repo, "pr")
    code, out = run_floor(repo, capsys)
    assert code == 1
    assert "tamper/hook-removed .cursor/hooks.json" in out


def test_removing_one_pre_tool_use_entry_names_the_event_and_command(tmp_path, capsys) -> None:
    repo = base_repo(tmp_path)
    settings = json.loads(json.dumps(CLAUDE))
    settings["hooks"]["PreToolUse"].pop(1)
    write(repo, ".claude/settings.json", settings)
    commit(repo, "pr")
    code, out = run_floor(repo, capsys)
    assert code == 1
    assert (
        "tamper/hook-removed .claude/settings.json: PreToolUse hook removed: sh .chock/bin/launch.sh claude.py --write"
        in out
    )
    assert out.count("tamper/hook-removed") == 1


def test_narrowing_a_hook_matcher_is_a_removal(tmp_path, capsys) -> None:
    repo = base_repo(tmp_path)
    settings = json.loads(json.dumps(CLAUDE))
    settings["hooks"]["PreToolUse"][1]["matcher"] = "Write"
    write(repo, ".claude/settings.json", settings)
    commit(repo, "pr")
    code, out = run_floor(repo, capsys)
    assert code == 1
    assert "tamper/hook-removed .claude/settings.json" in out


def test_a_regeneration_that_adds_a_policy_is_silent(tmp_path, capsys) -> None:
    """New policy, new index hash in every command, a widened matcher, a renamed index file: no tamper line."""
    repo = base_repo(tmp_path)
    settings = json.loads(json.dumps(CLAUDE))
    settings["hooks"]["PreToolUse"][0]["hooks"][0]["command"] = "sh .chock/bin/launch.sh claude.py --sha 99887766ff"
    settings["hooks"]["PreToolUse"][1]["matcher"] = "Write|Edit|MultiEdit"
    settings["hooks"]["Stop"] = [
        {"hooks": [{"type": "command", "command": "sh .chock/bin/launch.sh claude.py --stop"}]}
    ]
    write(repo, ".claude/settings.json", settings)
    cursor = json.loads(json.dumps(CURSOR))
    cursor["hooks"]["preToolUse"] = [{"command": "sh .chock/bin/launch.sh cursor.py --write"}]
    write(repo, ".cursor/hooks.json", cursor)
    (repo / ".chock/bin/index/claude-PreToolUse-3a2134a7.json").unlink()
    write(repo, ".chock/bin/index/claude-PreToolUse-77fe01bc.json", "{}\n")
    gate(repo, "new-policy", {**FLOOR_TOKEN, "params": {"content_pattern": "NEW-POLICY-[0-9]+"}})
    write(repo, "chock.lock", {**LOCK, "packs": [*LOCK["packs"], {"id": "new-policy"}]})
    write(repo, ".github/workflows/chock.yml", WORKFLOW.replace("0" * 40, "1" * 40))
    commit(repo, "regenerate")
    code, out = run_floor(repo, capsys)
    assert code == 0, out
    assert "tamper/" not in out


def test_removing_a_pack_from_the_lock_is_refused(tmp_path, capsys) -> None:
    repo = base_repo(tmp_path)
    write(repo, "chock.lock", {**LOCK, "packs": LOCK["packs"][:1]})
    commit(repo, "pr")
    code, out = run_floor(repo, capsys)
    assert code == 1
    assert "tamper/lock-pack-removed chock.lock: pack 'floor-token'" in out


def test_removing_the_floor_step_from_the_workflow_is_refused(tmp_path, capsys) -> None:
    repo = base_repo(tmp_path)
    write(repo, ".github/workflows/chock.yml", WORKFLOW.split("      - name: Floor")[0])
    commit(repo, "pr")
    code, out = run_floor(repo, capsys)
    assert code == 1
    assert "tamper/ci-step-removed .github/workflows/chock.yml: job 'floor': step 'Floor' removed" in out


def test_dropping_a_trigger_is_refused(tmp_path, capsys) -> None:
    repo = base_repo(tmp_path)
    write(repo, ".github/workflows/chock.yml", WORKFLOW.replace("  merge_group:\n", ""))
    commit(repo, "pr")
    code, out = run_floor(repo, capsys)
    assert code == 1
    assert "trigger 'merge_group' removed" in out


def test_the_guarded_workflow_is_named_by_the_base_config(tmp_path, capsys) -> None:
    repo = base_repo(tmp_path)
    (repo / ".github/workflows/chock.yml").rename(repo / ".github/workflows/floor.yml")
    write(repo, ".chock/config.yaml", "floor_workflow: .github/workflows/floor.yml\n")
    from floor_support import git

    git(repo, "checkout", "-q", "main")
    commit(repo, "move the workflow")
    git(repo, "checkout", "-q", "-B", "pr")
    (repo / ".github/workflows/floor.yml").unlink()
    commit(repo, "pr")
    code, out = run_floor(repo, capsys)
    assert code == 1
    assert "tamper/ci-step-removed .github/workflows/floor.yml" in out


def test_weakening_a_gate_action_or_binding_is_refused(tmp_path, capsys) -> None:
    repo = base_repo(tmp_path)
    gate(repo, "floor-token", {**FLOOR_TOKEN, "action": "warn", "on": ["tool_use"]}, surfaces=("git-hook",))
    commit(repo, "pr")
    code, out = run_floor(repo, capsys)
    assert code == 1
    assert "tamper/gate-weakened .chock/compiled/floor-token/git-hook/gate.json: no longer bound to: commit" in out
    assert "action block -> warn" in out


def test_deleting_a_compiled_gate_is_refused(tmp_path, capsys) -> None:
    repo = base_repo(tmp_path)
    (repo / ".chock/compiled/floor-token/ci-gate/gate.json").unlink()
    commit(repo, "pr")
    code, out = run_floor(repo, capsys)
    assert code == 1
    assert "tamper/gate-removed .chock/compiled/floor-token/ci-gate/gate.json" in out


def test_an_edited_runner_is_never_run_and_only_its_deletion_is_named(tmp_path, capsys) -> None:
    repo = base_repo(tmp_path)
    write(repo, ".chock/bin/gate.py", "raise SystemExit(0)\n")
    (repo / "tests/test_core.py").unlink()
    commit(repo, "pr")
    code, out = run_floor(repo, capsys)
    assert code == 1
    assert "tests/test_core.py: test file deleted" in out
    assert "tamper/runtime-removed" not in out
    (repo / ".chock/bin/gate.py").unlink()
    commit(repo, "pr 2")
    code, out = run_floor(repo, capsys)
    assert "tamper/runtime-removed .chock/bin/gate.py" in out
