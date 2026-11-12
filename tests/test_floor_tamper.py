"""`chock check --floor` refuses, by name, a removed or weakened guardrail, and stays silent on a regeneration."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from floor_support import (
    CLAUDE,
    CURSOR,
    FLOOR_TOKEN,
    LOCK,
    WORKFLOW,
    base_repo,
    commit,
    gate,
    git,
    run_floor,
    write,
)

ROOT = Path(__file__).resolve().parents[1]


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
        "tamper/hook-removed .claude/settings.json: PreToolUse command hook removed: "
        "sh .chock/bin/launch.sh claude.py --write" in out
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
    """New locked policy, a new index pin in a command, a widened matcher, a new hook: no tamper line."""
    repo = base_repo(tmp_path)
    settings = json.loads(json.dumps(CLAUDE))
    command = settings["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
    settings["hooks"]["PreToolUse"][0]["hooks"][0]["command"] = command[:-64] + "cd" * 32
    settings["hooks"]["PreToolUse"][1]["matcher"] = "Write|Edit|MultiEdit"
    settings["hooks"]["Stop"] = [
        {"hooks": [{"type": "command", "command": "sh .chock/bin/launch.sh claude.py --stop"}]}
    ]
    write(repo, ".claude/settings.json", settings)
    cursor = json.loads(json.dumps(CURSOR))
    cursor["hooks"]["preToolUse"] = [{"command": "sh .chock/bin/launch.sh cursor.py --write"}]
    write(repo, ".cursor/hooks.json", cursor)
    gate(repo, "new-policy", {**FLOOR_TOKEN, "params": {"content_pattern": "NEW-POLICY-[0-9]+"}})
    write(repo, "chock.lock", {**LOCK, "packs": [*LOCK["packs"], {"id": "new-policy"}]})
    commit(repo, "regenerate")
    code, out = run_floor(repo, capsys)
    assert code == 0, out
    assert "tamper/" not in out
    assert "floor/pack-changed: new-policy: lock entry changed; compiled: .chock/compiled/new-policy/" in out


def test_removing_a_pack_from_the_lock_is_refused(tmp_path, capsys) -> None:
    repo = base_repo(tmp_path)
    write(repo, "chock.lock", {**LOCK, "packs": LOCK["packs"][:1]})
    commit(repo, "pr")
    code, out = run_floor(repo, capsys)
    assert code == 1
    assert "tamper/lock-pack-removed chock.lock: pack 'floor-token'" in out


def test_any_edit_to_the_floor_workflow_is_refused(tmp_path, capsys) -> None:
    repo = base_repo(tmp_path)
    write(repo, ".github/workflows/chock.yml", WORKFLOW.split("      - name: Floor")[0])
    commit(repo, "pr")
    code, out = run_floor(repo, capsys)
    assert code == 1
    assert "tamper/floor-workflow-changed .github/workflows/chock.yml: neither the merge-base's bytes" in out
    assert "privileged merge" in out


def test_the_floor_workflow_may_become_what_this_engine_renders(tmp_path, capsys) -> None:
    from chock.scaffold import install_ci

    repo = base_repo(tmp_path)
    write(repo, ".github/workflows/chock.yml", install_ci.render())
    commit(repo, "regenerate the workflow")
    code, out = run_floor(repo, capsys)
    assert code == 0, out


def test_the_guarded_workflow_is_named_by_the_base_config(tmp_path, capsys) -> None:
    repo = base_repo(tmp_path)
    git(repo, "checkout", "-q", "main")
    (repo / ".github/workflows/chock.yml").rename(repo / ".github/workflows/floor.yml")
    write(repo, ".chock/config.yaml", "floor_workflow: .github/workflows/floor.yml\n")
    commit(repo, "move the workflow")
    git(repo, "checkout", "-q", "-B", "pr")
    (repo / ".github/workflows/floor.yml").unlink()
    commit(repo, "pr")
    code, out = run_floor(repo, capsys)
    assert code == 1
    assert "tamper/floor-workflow-changed .github/workflows/floor.yml: the floor's workflow was deleted" in out


def test_weakening_a_gate_without_a_lock_change_is_refused(tmp_path, capsys) -> None:
    repo = base_repo(tmp_path)
    gate(repo, "floor-token", {**FLOOR_TOKEN, "action": "warn", "on": ["tool_use"]}, surfaces=("git-hook",))
    commit(repo, "pr")
    code, out = run_floor(repo, capsys)
    assert code == 1
    assert "tamper/gate-changed .chock/compiled/floor-token/git-hook/gate.json: no longer bound to: commit" in out
    assert "chock.lock has no change for 'floor-token'" in out


def test_a_gate_change_with_a_lock_change_is_listed_not_refused(tmp_path, capsys) -> None:
    repo = base_repo(tmp_path)
    gate(repo, "floor-token", {**FLOOR_TOKEN, "message": "Still no floor tokens."})
    write(repo, "chock.lock", {**LOCK, "packs": [LOCK["packs"][0], {"id": "floor-token", "version": "2"}]})
    commit(repo, "upgrade floor-token")
    code, out = run_floor(repo, capsys)
    assert code == 0, out
    assert "floor/pack-changed: floor-token: lock entry changed; compiled: " in out
    assert ".chock/compiled/floor-token/ci-gate/gate.json, .chock/compiled/floor-token/git-hook/gate.json" in out
    assert "cannot tell a policy upgrade from a policy weakening offline" in out


def test_deleting_a_compiled_gate_is_refused(tmp_path, capsys) -> None:
    repo = base_repo(tmp_path)
    (repo / ".chock/compiled/floor-token/ci-gate/gate.json").unlink()
    commit(repo, "pr")
    code, out = run_floor(repo, capsys)
    assert code == 1
    assert "tamper/gate-removed .chock/compiled/floor-token/ci-gate/gate.json" in out


def test_an_edited_runner_is_never_run_and_is_refused(tmp_path, capsys) -> None:
    repo = base_repo(tmp_path)
    write(repo, ".chock/bin/gate.py", "raise SystemExit(0)\n")
    (repo / "tests/test_core.py").unlink()
    commit(repo, "pr")
    code, out = run_floor(repo, capsys)
    assert code == 1
    assert "tests/test_core.py: test file deleted" in out
    assert "tamper/runtime-changed .chock/bin/gate.py" in out
    (repo / ".chock/bin/gate.py").unlink()
    commit(repo, "pr 2")
    code, out = run_floor(repo, capsys)
    assert "tamper/runtime-removed .chock/bin/gate.py" in out


def test_a_runtime_may_become_what_this_engine_renders(tmp_path, capsys) -> None:
    from chock.gate.assemble import runner_source
    from chock.hooks.launch import launcher_text

    repo = base_repo(tmp_path)
    write(repo, ".chock/bin/gate.py", runner_source())
    write(repo, ".chock/bin/launch.sh", launcher_text())
    commit(repo, "regenerate the runtime")
    code, out = run_floor(repo, capsys)
    assert code == 0, out


def _real_install(tmp_path: Path) -> tuple[Path, str]:
    """A base carrying this repository's own compiled policies, Claude Code hooks and their pinned indexes."""
    repo = tmp_path / "real"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    for rel in (".chock/compiled", ".agents/policies"):
        shutil.copytree(ROOT / rel, repo / rel)
    for rel in (".claude/settings.json", ".chock/config.yaml"):
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / rel, repo / rel)
    index = sorted((ROOT / ".chock/bin/index").glob("claude_code-*.json"))[0]
    rel = f".chock/bin/index/{index.name}"
    (repo / rel).parent.mkdir(parents=True, exist_ok=True)
    (repo / rel).write_text("{}\n", encoding="utf-8")
    commit(repo, "base: a stale index")
    git(repo, "checkout", "-q", "-b", "pr")
    return repo, rel


def test_an_index_this_engine_renders_is_accepted_and_any_other_refused(tmp_path, capsys) -> None:
    repo, rel = _real_install(tmp_path)
    shutil.copy2(ROOT / rel, repo / rel)
    commit(repo, "sync rewrites the index")
    code, out = run_floor(repo, capsys, "--head-ref", "pr")
    assert code == 0, out
    write(repo, rel, json.loads((ROOT / rel).read_text(encoding="utf-8")) | {"members": []})
    commit(repo, "an index that runs nothing")
    code, out = run_floor(repo, capsys, "--head-ref", "pr")
    assert code == 1
    assert f"tamper/runtime-changed {rel}" in out
