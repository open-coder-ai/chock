"""Copilot's content-gate wiring: a PreToolUse write gate and a Stop gate in chock's own hooks file.

Payload shapes are the ones captured live in VS Code Copilot Chat agent mode (2026-09-28): an edit is
`Edit {path, old_str, new_str}`, a create is `Write {path, file_text}`, both snake_case with
`hook_event_name` and `timestamp`; a top-level `permissionDecision: deny` stopped an `Edit`.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
import yaml
from conftest import run_hook_command

from chock.compile.compiler import compile_policy
from chock.compile.emitters.in_agent import COPILOT_WRITE_MATCHER, SHELL_MATCHER, emit_agent_hooks
from chock.gate import runtime_bundle
from chock.hooks.in_agent_install import agent_hooks_rel, install_hooks, installed_policy_ids, uninstall_hooks

SECRET = "AKIA" + "1234567890ABCDEF"  # pragma: allowlist secret
POLICY_ID = "leaky"
VENDOR = "vscode_copilot"
ENTRY_KEYS = {"type", "timeout", "timeoutSec", "bash", "command", "powershell", "windows"}
STAMP = "2026-09-28T09:00:00.000Z"


def _repo(tmp_path: Path, *, install: bool = True) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    policy = repo / ".agents" / "policies" / POLICY_ID
    policy.mkdir(parents=True)
    manifest = {
        "id": POLICY_ID,
        "name": "Leaky",
        "version": "0.0.1",
        "description": "d",
        "artifact": "hook",
        "enforcement": "block",
        "hook": {
            "gate": {
                "kind": "content_regex",
                "on": ["commit", "tool_use"],
                "action": "block",
                "message": "secret-shaped string in what was written",
                "params": {"scan": "added_lines", "content_pattern": r"AKIA[0-9A-Z]{16}"},
            }
        },
        "provenance": {"author": "t"},
        "lifecycle": {"status": "draft"},
    }
    (policy / "manifest.yaml").write_text(yaml.safe_dump(manifest), encoding="utf-8")
    compile_policy(policy, output_root=repo / ".chock" / "compiled", repo_root=repo)
    if install:
        install_hooks(repo, VENDOR)
    return repo


def _hooks(repo: Path) -> dict:
    return json.loads((repo / agent_hooks_rel()).read_text(encoding="utf-8"))["hooks"]


def _pre(tool: str, tool_input: dict, cwd: Path) -> str:
    return json.dumps(
        {
            "hook_event_name": "PreToolUse",
            "session_id": "s1",
            "timestamp": STAMP,
            "cwd": str(cwd),
            "tool_name": tool,
            "tool_input": tool_input,
        }
    )


def _stop(cwd: Path, *, active: bool = False) -> str:
    return json.dumps(
        {
            "hook_event_name": "Stop",
            "session_id": "s1",
            "timestamp": STAMP,
            "cwd": str(cwd),
            "transcript_path": str(cwd / "t.jsonl"),
            "stop_reason": "end_turn",
            "stop_hook_active": active,
        }
    )


def _run(repo: Path, event: str, payload: str) -> subprocess.CompletedProcess:
    proc = run_hook_command(_hooks(repo)[event][0]["bash"], repo, payload)
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    return proc


def _edit(repo: Path, new: str) -> str:
    target = repo / "Config.java"
    target.write_text('String key = "none";\n', encoding="utf-8")
    return _pre("Edit", {"path": str(target), "old_str": 'String key = "none";', "new_str": new}, repo)


# --- what is emitted and installed ---------------------------------------------------------------


def test_the_installed_file_carries_a_write_gate_and_a_stop_gate_in_the_witnessed_entry_shape(tmp_path: Path) -> None:
    hooks = _hooks(_repo(tmp_path))
    (pre,) = hooks["PreToolUse"]
    (stop,) = hooks["Stop"]
    assert set(pre) == ENTRY_KEYS | {"matcher"}
    assert pre["matcher"] == COPILOT_WRITE_MATCHER == "Edit|Write"
    assert set(stop) == ENTRY_KEYS, "a turn end has no tool to match"
    for entry, surface in ((pre, "agent-hooks"), (stop, "stop")):
        assert entry["bash"] == entry["command"]
        assert entry["powershell"] == entry["windows"]
        assert entry["powershell"].startswith("& ") and "exit 2" in entry["powershell"]
        assert "--gate" in entry["bash"] and f"/{POLICY_ID}/{surface}/gate.json" in entry["bash"]
    assert "agentStop" not in hooks, "Copilot fires agentStop beside Stop: registering both runs the gate twice"


def test_a_guard_policy_is_emitted_as_before_and_gets_no_gate_entries(tmp_path: Path) -> None:
    pol = tmp_path / ".agents" / "policies" / "block-destructive-commands"
    (pol / "implementations").mkdir(parents=True)
    (pol / "implementations" / "block-destructive.sh").write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    out = tmp_path / "out"
    written = emit_agent_hooks(pol, out, {"id": "block-destructive-commands"})
    assert [p.name for p in written] == ["agent-hooks.json"]
    entry = json.loads(written[0].read_text(encoding="utf-8"))
    assert set(entry) == ENTRY_KEYS | {"matcher"}
    assert entry["matcher"] == SHELL_MATCHER
    assert "--guard" in entry["bash"]


def test_install_is_idempotent_and_uninstall_removes_the_file(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    first = (repo / agent_hooks_rel()).read_bytes()
    assert install_hooks(repo, VENDOR) == [POLICY_ID]
    assert (repo / agent_hooks_rel()).read_bytes() == first
    assert installed_policy_ids(repo, VENDOR) == {POLICY_ID}
    uninstall_hooks(repo, VENDOR)
    assert not (repo / agent_hooks_rel()).exists()
    assert installed_policy_ids(repo, VENDOR) == set()


# --- coverage rises only when the entries are installed ---------------------------------------------


def _levels(repo: Path) -> dict[str, str]:
    result = compile_policy(
        repo / ".agents" / "policies" / POLICY_ID,
        output_root=repo / ".chock" / "compiled",
        repo_root=repo,
        agents=["copilot", "vscode"],
    )
    return {agent: cell["level"] for agent, cell in result.coverage[POLICY_ID].items()}


def test_coverage_is_commit_time_until_the_entries_are_installed(tmp_path: Path) -> None:
    repo = _repo(tmp_path, install=False)
    assert _levels(repo) == {"copilot": "enforced-at-commit", "vscode": "enforced-at-commit"}
    install_hooks(repo, VENDOR)
    after = _levels(repo)
    assert after["copilot"] == after["vscode"] != "enforced-at-commit"
    (repo / agent_hooks_rel()).unlink()
    assert _levels(repo)["copilot"] == "enforced-at-commit"


def test_an_installed_file_missing_the_stop_entry_does_not_read_back_as_installed(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    path = repo / agent_hooks_rel()
    doc = json.loads(path.read_text(encoding="utf-8"))
    del doc["hooks"]["Stop"]
    path.write_text(json.dumps(doc), encoding="utf-8")
    assert installed_policy_ids(repo, VENDOR) == set()


# --- the installed commands, run the way Copilot runs them -----------------------------------------


def _denies(proc: subprocess.CompletedProcess) -> str:
    body = json.loads(proc.stdout)
    assert body["permissionDecision"] == "deny", "the witnessed top-level shape"
    assert "hookSpecificOutput" in body, "the nested dialect agentseam writes is kept beside it"
    assert body["hookSpecificOutput"]["permissionDecision"] == "deny"
    return body["permissionDecisionReason"]


def test_an_edit_that_adds_a_denied_construct_is_denied(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    reason = _denies(_run(repo, "PreToolUse", _edit(repo, f'String key = "{SECRET}";')))
    assert "secret-shaped" in reason


def test_an_edit_that_fixes_it_is_allowed_silently(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    assert _run(repo, "PreToolUse", _edit(repo, 'String key = System.getenv("KEY");')).stdout.strip() == ""


def test_a_relative_edit_path_is_judged_from_the_repo(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    payload = json.loads(_edit(repo, f'String key = "{SECRET}";'))
    payload["tool_input"]["path"] = "Config.java"
    _denies(_run(repo, "PreToolUse", json.dumps(payload)))


def test_a_write_of_a_whole_new_file_is_judged_by_its_file_text(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    target = str(repo / "New.java")
    bad = _pre("Write", {"path": target, "file_text": f'class N {{ String k = "{SECRET}"; }}\n'}, repo)
    _denies(_run(repo, "PreToolUse", bad))
    good = _pre("Write", {"path": target, "file_text": "class N { }\n"}, repo)
    assert _run(repo, "PreToolUse", good).stdout.strip() == ""


@pytest.mark.parametrize(
    ("tool", "tool_input"),
    [
        ("Read", {"path": "Config.java"}),
        ("Grep", {"pattern": "AKIA", "paths": ["."], "output_mode": "content"}),
        ("Bash", {"command": f"echo {SECRET}", "description": "d", "mode": "sync"}),
    ],
)
def test_an_unrelated_tool_is_allowed_silently(tmp_path: Path, tool: str, tool_input: dict) -> None:
    repo = _repo(tmp_path)
    assert _run(repo, "PreToolUse", _pre(tool, tool_input, repo)).stdout.strip() == ""


def test_a_turn_that_left_a_denied_construct_on_disk_is_blocked_at_its_end(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    (repo / "Leak.java").write_text(f'String k = "{SECRET}";\n', encoding="utf-8")
    body = json.loads(_run(repo, "Stop", _stop(repo)).stdout)
    assert body["decision"] == "block" and "secret-shaped" in body["reason"], "top-level, as witnessed"
    nested = body["hookSpecificOutput"]
    assert (nested["hookEventName"], nested["decision"], nested["reason"]) == ("Stop", "block", body["reason"])


def test_a_clean_turn_and_a_re_entered_stop_are_allowed_silently(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    (repo / "Fine.java").write_text("class Fine { }\n", encoding="utf-8")
    assert _run(repo, "Stop", _stop(repo)).stdout.strip() == ""
    (repo / "Leak.java").write_text(f'String k = "{SECRET}";\n', encoding="utf-8")
    assert _run(repo, "Stop", _stop(repo, active=True)).stdout.strip() == "", "no loop on the retry"


def test_only_the_copilot_runtime_carries_the_top_level_answer() -> None:
    """Every other vendor's refusal is exactly what agentseam writes."""
    for agent in runtime_bundle.RUNTIME_AGENTS:
        assert ("_chock_copilot_respond" in runtime_bundle.render(agent)) == (agent == VENDOR), agent
