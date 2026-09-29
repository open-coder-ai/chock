"""Shared fixtures for the tool_call / outside_repo / session-log tests: a compiled repo and a fired hook."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import yaml

from chock.compile.compiler import compile_policy

POLICY_ID = "guard-tools"
#: Reads the payload a tool_call script gets and blocks Firecrawl unless the session says otherwise.
SCRIPT = """\
import json, sys

payload = json.load(sys.stdin)
assert payload["event"] == "tool_call", payload
open(payload["repo_root"] + "/payload.json", "w").write(json.dumps(payload))
if payload["input"].get("url", "").endswith("/blocked"):
    sys.stderr.write("that URL is blocked here")
    sys.exit(1)
if payload["input"].get("url", "").endswith("/crash"):
    sys.exit(7)
"""


def init_git(repo: Path) -> None:
    subprocess.run(["git", "init", "-q", str(repo)], check=True)


def make_repo(tmp_path: Path, gate: dict[str, Any], script: str | None = None, applies_to: dict | None = None) -> Path:
    """A git repo with one policy carrying `gate`, compiled the way `chock sync` would."""
    repo = tmp_path / "repo"
    repo.mkdir()
    init_git(repo)
    policy = repo / ".agents" / "policies" / POLICY_ID
    policy.mkdir(parents=True)
    manifest: dict[str, Any] = {
        "id": POLICY_ID,
        "name": "Guard tools",
        "version": "0.0.1",
        "description": "d",
        "artifact": "hook",
        "enforcement": "block",
        "hook": {"gate": {"action": "block", "message": "tool call refused by policy", **gate}},
        "provenance": {"author": "t"},
        "lifecycle": {"status": "draft"},
    }
    if applies_to:
        manifest["applies_to"] = applies_to
    (policy / "manifest.yaml").write_text(yaml.safe_dump(manifest), encoding="utf-8")
    if script is not None:
        (policy / "implementations").mkdir()
        (policy / "implementations" / "judge.py").write_text(script, encoding="utf-8")
    compile_policy(policy, output_root=repo / ".chock" / "compiled", repo_root=repo)
    return repo


def tool_call_gate(script: bool = False) -> dict[str, Any]:
    """A tool_call gate: a script gate for Firecrawl tools, or (default) a content regex over WebFetch and MCP input."""
    if script:
        return {"kind": "script", "on": ["tool_call"], "params": {"script": "judge.py", "tools": ["mcp__Firecrawl__*"]}}
    return {
        "kind": "content_regex",
        "on": ["tool_call"],
        "params": {"content_pattern": "evil\\.example", "tools": ["WebFetch", "mcp__*"]},
    }


def fire(
    repo: Path, args: list[str], payload: dict[str, Any], vendor: str = "claude_code"
) -> subprocess.CompletedProcess:
    """Run the vendored runtime the way an agent's hook does, with `args` as its command line."""
    runtime = repo / ".chock" / "bin" / f"{vendor}.py"
    return subprocess.run(
        [shutil.which("python3") or "python3", str(runtime), *args],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        cwd=str(repo),
        check=False,
    )


def pre_payload(repo: Path, tool: str, tool_input: dict[str, Any], session: str = "sess-1", call: str = "t1") -> dict:
    return {
        "hook_event_name": "PreToolUse",
        "tool_name": tool,
        "tool_input": tool_input,
        "session_id": session,
        "tool_use_id": call,
        "cwd": str(repo),
    }


def log_lines(repo: Path, session: str = "sess-1") -> list[dict[str, Any]]:
    path = repo / ".chock" / "state" / f"{session}.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
