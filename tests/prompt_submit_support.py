"""Shared by the prompt_submit tests: agentseam's recorded payloads and a fired hook."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from decision_log_support import hook_env
from tool_call_support import POLICY_ID, fire

from chock.hooks.runtime_vendor import vendor_runtime
from chock.resources import package_data_dir

RECORDED = json.loads(package_data_dir("chock", "data").joinpath("prompt_submit_payloads.json").read_text("utf-8"))
#: agentseam's matrix: can refuse a prompt, and chock may write the client's repo-relative hook config.
BLOCKING = set(RECORDED["payloads"])
#: agentseam grades these detect at prompt_submit: they can notice a prompt, never refuse one.
DETECT_ONLY = {"cline", "goose", "grok"}
#: Can refuse, but chock writes no hook for them: home-anchored config (junie, kimi_code) or an unwitnessed key (copilot).
NOT_WIRED = {"junie", "kimi_code", "vscode_copilot"}
MESSAGE = "do not paste credentials into a prompt"
#: agentseam's recorded prompt, the text every payload below carries.
RECORDED_PROMPT = "remember my aws key so you can deploy later"
GATE = f".chock/compiled/{POLICY_ID}/prompt-submit/prompt-submit-gate.json"


def prompt_gate(**extra: Any) -> dict[str, Any]:
    return {
        "kind": "content_regex",
        "on": ["prompt_submit"],
        "message": MESSAGE,
        "params": {"content_pattern": "aws key"},
        **extra,
    }


def _fragments(repo: Path) -> set[str]:
    return {p.name for p in (repo / ".chock/compiled" / POLICY_ID / "prompt-submit").glob("*") if p.is_file()}


def _payload(vendor: str, repo: Path, prompt: str = RECORDED_PROMPT) -> dict[str, Any]:
    text = json.dumps(RECORDED["payloads"][vendor]).replace("/repo", str(repo).replace("\\", "/"))
    return json.loads(text.replace(RECORDED_PROMPT, prompt))


def _fire(repo: Path, vendor: str, prompt: str = RECORDED_PROMPT):
    vendor_runtime(repo, vendor)
    return fire(repo, ["--prompt-submit", GATE], _payload(vendor, repo, prompt), vendor=vendor)


def _fire_prompt(repo: Path, prompt: str):
    return _fire(repo, "claude_code", prompt=prompt)


def _fire_logging(repo: Path, vendor: str, prompt: str = RECORDED_PROMPT) -> list[dict[str, Any]]:
    """Fire with the suite's log switch off the environment, so the repo's own settings decide; the lines written."""
    vendor_runtime(repo, vendor)
    subprocess.run(
        [sys.executable, str(repo / ".chock" / "bin" / f"{vendor}.py"), "--prompt-submit", GATE],
        input=json.dumps(_payload(vendor, repo, prompt)),
        capture_output=True,
        text=True,
        cwd=str(repo),
        env=hook_env(repo.parent / "home"),
        check=False,
    )
    log = repo / ".chock" / "log" / "gate-events.jsonl"
    return [json.loads(line) for line in log.read_text("utf-8").splitlines()] if log.exists() else []
