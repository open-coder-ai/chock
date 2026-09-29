"""A tool_call script speaks ask (exit 3) and warn (exit 4) too, held to the gate's declared action."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tool_call_support import fire, make_repo, pre_payload, tool_call_gate

from chock.gate.tool_call_gate import _tool_call_capped
from chock.hooks.in_agent_install import install_hooks

SPEAKS = """\
import json, sys

code = int(json.load(sys.stdin)["input"]["code"])
sys.stderr.write(f"judge spoke {code}")
sys.exit(code)
"""


def _answer(tmp_path: Path, action: str, code: int) -> dict:
    repo = make_repo(tmp_path, {**tool_call_gate(script=True), "action": action}, script=SPEAKS)
    install_hooks(repo, "claude_code")
    gate = ".chock/compiled/guard-tools/pre-tool-use/tool-call-gate.json"
    proc = fire(repo, ["--tool-call", gate], pre_payload(repo, "mcp__Firecrawl__firecrawl_scrape", {"code": code}))
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout or "{}").get("hookSpecificOutput", {})


def test_exit_3_asks_the_person(tmp_path: Path) -> None:
    out = _answer(tmp_path, "block", 3)
    assert out["permissionDecision"] == "ask"
    assert "judge spoke 3" in out["permissionDecisionReason"]


def test_exit_4_warns_without_touching_the_permission_prompt(tmp_path: Path) -> None:
    out = _answer(tmp_path, "block", 4)
    assert "judge spoke 4" in out["additionalContext"]
    assert "permissionDecision" not in out


def test_a_warn_gate_never_denies_even_when_its_script_does(tmp_path: Path) -> None:
    out = _answer(tmp_path, "warn", 1)
    assert "permissionDecision" not in out
    assert "judge spoke 1" in out["additionalContext"]


@pytest.mark.parametrize(
    ("action", "spoken", "held"),
    [
        ("block", "deny", "deny"),
        ("block", "warn", "warn"),
        ("ask", "deny", "escalate"),
        ("ask", "warn", "warn"),
        ("warn", "escalate", "warn"),
    ],
)
def test_the_declared_action_is_a_ceiling(action: str, spoken: str, held: str) -> None:
    assert _tool_call_capped({"action": action}, (spoken, "why")) == (held, "why")


def test_an_allow_stays_an_allow() -> None:
    assert _tool_call_capped({"action": "warn"}, None) is None
