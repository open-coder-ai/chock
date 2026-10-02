"""A policy with a shell guard AND a tool_use gate ships both in its plugin, in every store.

Before, a guard displaced the gate: a plugin-only install of protect-agent-config refused a
shell write to a protected path and let an Edit to the same path through, while its skill and
description named the policy as enforced. Each half now ships where the client runs it, and
the package states exactly the halves it carries. A policy with one half packages as before.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest
from conftest import init_repo, run_hook_command
from guard_gate_support import BUILDERS, DIFFERS, POLICY_ID, PROTECTED, STORES, golden_of, make_policy

from chock.plugin import bundle_grade, gate_package, guard_gate
from chock.plugin.cli import main as plugin_main

GOLDEN = Path(__file__).parent / "fixtures" / "plugin_single_half_golden.json"


def _commands(doc: dict, flag: str) -> list[str]:
    return [c for c in bundle_grade._hook_commands(doc) if flag in c]


@pytest.mark.parametrize("store", sorted(STORES))
def test_both_halves_ship_in_every_store(tmp_path: Path, store: str) -> None:
    agent, files_fn, hooks_rel = STORES[store]
    pack, data = make_policy(tmp_path, guard=True, gate=True)
    files = files_fn(pack, data, tmp_path)

    doc = json.loads(files[Path(hooks_rel)])
    assert _commands(doc, "--guard"), "the guard still ships"
    assert _commands(doc, "--gate"), "and the gate beside it"
    assert files[Path(f"scripts/{POLICY_ID}.py")].startswith("import sys")
    assert json.loads(files[Path("scripts/gate.json")])["params"]["forbidden_path_regex"] == r"\.mcp\.json"
    assert Path("scripts/gate.py") in files

    matcher, stop = gate_package.gate_reach(agent)
    gate_events = bundle_grade.events_for(doc, "--gate")
    assert (len(gate_events) == 2) == (matcher is not None and stop)
    grade, says = bundle_grade.grade_of_files(files, hooks_rel, agent)
    assert says.startswith("refuses a matched shell command before it runs; blocks ")
    assert ("the write itself is not judged" in says) == (matcher is None), "a Stop-only gate never claims the write"
    assert grade == (bundle_grade.BLOCKS if matcher else bundle_grade.STOP_ONLY)


@pytest.mark.parametrize("store", sorted(STORES))
def test_the_package_states_both_halves_and_nothing_advisory(tmp_path: Path, store: str) -> None:
    _, files_fn, _ = STORES[store]
    pack, data = make_policy(tmp_path, guard=True, gate=True)
    files = files_fn(pack, data, tmp_path)
    manifest_text = next(text for rel, text in files.items() if rel.name == "plugin.json")
    description = json.loads(manifest_text)["description"]
    assert "Shell guard:" in description and "Write gate:" in description
    assert "Advisory skill only" not in description
    skill = next(text for rel, text in files.items() if rel.name == "SKILL.md")
    assert "Its write gate " in skill
    assert skill.count("Repo-wide") == 1, "the guard's closing sentence is not repeated"


def test_a_gate_the_client_cannot_run_is_neither_shipped_nor_claimed(tmp_path: Path, monkeypatch) -> None:
    """Where agentseam records no gate surface, the package is the guard alone, and says only that."""
    pack, data = make_policy(tmp_path, guard=True, gate=True)
    monkeypatch.setattr(gate_package, "gate_reaches", lambda _vendor: False)
    files = STORES["codex"][1](pack, data, tmp_path)
    doc = json.loads(files[Path(STORES["codex"][2])])
    assert _commands(doc, "--guard") and not _commands(doc, "--gate")
    assert Path("scripts/gate.json") not in files
    description = json.loads(files[Path(".codex-plugin/plugin.json")])["description"]
    assert "Write gate:" not in description and "Stop" not in description
    skill = next(text for rel, text in files.items() if rel.name == "SKILL.md")
    assert "Its write gate" not in skill


@pytest.mark.parametrize("half", ["guard", "gate"])
@pytest.mark.parametrize("store", sorted(STORES))
def test_one_half_packages_byte_for_byte_as_before(tmp_path: Path, store: str, half: str) -> None:
    """Golden taken from the engine before this change; runtime copies excluded (they follow the engine)."""
    pack, data = make_policy(tmp_path, guard=half == "guard", gate=half == "gate")
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))[f"{half}/{store}"]
    assert golden_of(STORES[store][1](pack, data, tmp_path)) == golden


@pytest.mark.parametrize("store", sorted(STORES))
def test_check_reports_a_package_built_with_the_guard_alone(tmp_path: Path, store: str) -> None:
    pack, data = make_policy(tmp_path, guard=True, gate=True)
    out = tmp_path / "dist" / store / POLICY_ID
    BUILDERS[store](pack, data, tmp_path, out)
    assert DIFFERS[store](pack, data, tmp_path, out) == []
    (out / "scripts" / "gate.json").unlink()
    assert any("gate.json" in d for d in DIFFERS[store](pack, data, tmp_path, out))


def test_the_cli_check_fails_on_a_tree_missing_the_gate(tmp_path: Path, capsys) -> None:
    make_policy(tmp_path, guard=True, gate=True)
    dist = tmp_path / "dist"
    args = ["build", "--repo", str(tmp_path), "--format", "claude", "--out-dir", str(dist)]
    assert plugin_main(args) == 0
    assert "ships both" in capsys.readouterr().out
    assert plugin_main([*args, "--check"]) == 0
    (dist / "claude" / POLICY_ID / "scripts" / "gate.json").unlink()
    assert plugin_main([*args, "--check"]) == 1


# --- and a plugin-only install refuses both ways in -------------------------------------------


def _claude_package(tmp_path: Path) -> tuple[Path, Path]:
    pack, data = make_policy(tmp_path, guard=True, gate=True)
    out = tmp_path / "plugin"
    BUILDERS["claude"](pack, data, tmp_path, out)
    repo = tmp_path / "project"
    repo.mkdir()
    init_repo(repo)
    (repo / PROTECTED).write_text("{}\n", encoding="utf-8")
    (repo / "notes.md").write_text("a\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=repo, check=True)
    return out, repo


def _decide(out: Path, repo: Path, tool: str, tool_input: dict, *, honour_matchers: bool = True) -> list[str]:
    """Every PreToolUse entry Claude Code would run for `tool` (or all of them), and what each said."""
    hooks = json.loads((out / "hooks" / "hooks.json").read_text(encoding="utf-8"))["hooks"]["PreToolUse"]
    payload = {"hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": tool_input, "cwd": str(repo)}
    said = []
    for entry in hooks:
        if honour_matchers and not re.fullmatch(entry["matcher"], tool):
            continue
        command = entry["hooks"][0]["command"].replace("${CLAUDE_PLUGIN_ROOT}", out.as_posix())
        proc = run_hook_command(command, repo, json.dumps(payload))
        assert proc.returncode == 0, proc.stderr
        said.append(json.loads(proc.stdout)["hookSpecificOutput"]["permissionDecision"] if proc.stdout else "allow")
    return said


def test_a_plugin_only_install_refuses_an_edit_and_a_shell_write(tmp_path: Path) -> None:
    out, repo = _claude_package(tmp_path)
    edit = {"file_path": str(repo / PROTECTED), "old_string": "{}", "new_string": '{"x": 1}'}
    assert _decide(out, repo, "Edit", edit) == ["deny"]
    write = {"file_path": str(repo / PROTECTED), "content": "{}"}
    assert _decide(out, repo, "Write", write) == ["deny"]
    assert _decide(out, repo, "Bash", {"command": f"echo '{{}}' > {PROTECTED}"}) == ["deny"]


def test_ordinary_work_passes_both_halves(tmp_path: Path) -> None:
    out, repo = _claude_package(tmp_path)
    edit = {"file_path": str(repo / "notes.md"), "old_string": "a", "new_string": "b"}
    assert _decide(out, repo, "Edit", edit) == ["allow"]
    assert _decide(out, repo, "Bash", {"command": "git status"}) == ["allow"]


def test_a_client_that_ignores_matchers_gets_no_cross_refusal(tmp_path: Path) -> None:
    """VS Code runs every entry for every tool: the guard must not judge an Edit, nor the gate a command."""
    out, repo = _claude_package(tmp_path)
    edit = {"file_path": str(repo / "notes.md"), "old_string": "a", "new_string": "b"}
    assert _decide(out, repo, "Edit", edit, honour_matchers=False) == ["allow", "allow"]
    assert _decide(out, repo, "Bash", {"command": "ls"}, honour_matchers=False) == ["allow", "allow"]
    protected = {"file_path": str(repo / PROTECTED), "old_string": "{}", "new_string": "[]"}
    assert "deny" in _decide(out, repo, "Edit", protected, honour_matchers=False)


# --- the merge itself -------------------------------------------------------------------------


def test_halves_that_disagree_on_a_path_or_a_setting_refuse_to_package() -> None:
    with pytest.raises(guard_gate.PackageCollisionError, match="version"):
        guard_gate.merge_hooks({"version": 1, "hooks": {}}, {"version": 2, "hooks": {}})
    files = {Path("scripts/gate.py"): "runner"}
    with pytest.raises(guard_gate.PackageCollisionError, match="scripts/gate.py"):
        guard_gate.place(files, {Path("scripts/gate.py"): "a guard named gate"})
    guard_gate.place(files, {Path("scripts/gate.py"): "runner"})


def test_a_guard_named_like_the_runner_cannot_overwrite_it(tmp_path: Path) -> None:
    pack, data = make_policy(tmp_path, guard=True, gate=True, policy_id="gate")
    with pytest.raises(guard_gate.PackageCollisionError, match="scripts/gate.py"):
        STORES["claude"][1](pack, data, tmp_path)
