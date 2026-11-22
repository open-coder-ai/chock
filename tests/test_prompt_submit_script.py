"""The `prompt_submit` script kind: its payload, its exit codes, and that none of its words reach a refusal."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from prompt_submit_support import MESSAGE, RECORDED_PROMPT, _fire, _fire_prompt
from tool_call_support import POLICY_ID, make_repo

SCRIPT = """\
import json, sys

payload = json.load(sys.stdin)
assert payload["event"] == "prompt_submit", payload
assert set(payload) == {"event", "repo_root", "prompt", "session"}, sorted(payload)
open(payload["repo_root"] + "/payload.json", "w").write(json.dumps(payload))
if "aws key" in payload["prompt"]:
    sys.stderr.write("script says no")
    sys.exit(1)
"""


def test_a_script_gate_gets_the_documented_payload_and_its_refusal_never_carries_the_prompt(tmp_path: Path) -> None:
    gate = {"kind": "script", "on": ["prompt_submit"], "message": MESSAGE, "params": {"script": "judge.py"}}
    repo = make_repo(tmp_path, gate, script=SCRIPT)
    proc = _fire(repo, "claude_code")
    assert json.loads(proc.stdout) == {"decision": "block", "reason": MESSAGE}
    seen = json.loads((repo / "payload.json").read_text())
    assert seen["prompt"] == RECORDED_PROMPT and seen["repo_root"] == str(repo)
    assert set(seen["session"]) == {"id", "log_path", "tool_use_id"}


LEAKY = """\
import sys, json

p = json.load(sys.stdin)["prompt"]
print("found key " + {tail})
sys.exit({code})
"""
LEAK_PROMPT = "deploy with " + "AKIA" + "IOSFODNN7EXAMPLE"


@pytest.mark.parametrize("code", [1, 3, 4, 7])
@pytest.mark.parametrize("tail", ["p.split()[-1]", "p.split()[-1][:4]", "p"])
def test_no_script_output_reaches_the_refusal_even_a_fragment_of_the_prompt(
    tmp_path: Path, code: int, tail: str
) -> None:
    gate = {"kind": "script", "on": ["prompt_submit"], "message": MESSAGE, "params": {"script": "judge.py"}}
    repo = make_repo(tmp_path, gate, script=LEAKY.format(tail=tail, code=code))
    proc = _fire_prompt(repo, LEAK_PROMPT)
    said = proc.stdout + proc.stderr
    assert "AKIA" not in said and "found key" not in said, said
    if code == 4:  # a warning never refuses
        return
    reason = json.loads(proc.stdout)["reason"]
    assert reason.startswith(MESSAGE) or (code == 7 and "exited 7" in reason and POLICY_ID in reason)


def test_a_timeout_or_missing_script_is_a_fixed_message_naming_the_policy(tmp_path: Path) -> None:
    gate = {"kind": "script", "on": ["prompt_submit"], "message": MESSAGE, "params": {"script": "judge.py"}}
    repo = make_repo(tmp_path, gate)  # the script is never shipped
    reason = json.loads(_fire_prompt(repo, LEAK_PROMPT).stdout)["reason"]
    assert POLICY_ID in reason and "not installed" in reason and "AKIA" not in reason


def test_a_script_that_crashes_refuses(tmp_path: Path) -> None:
    gate = {"kind": "script", "on": ["prompt_submit"], "message": MESSAGE, "params": {"script": "judge.py"}}
    repo = make_repo(tmp_path, gate, script="import sys\nsys.exit(7)\n")
    assert json.loads(_fire(repo, "claude_code").stdout)["decision"] == "block"
