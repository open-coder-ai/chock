"""The `tool_call` event: a gate declared by tool name is emitted where the vendor evidence allows, and refuses."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tool_call_support import POLICY_ID, SCRIPT, fire, make_repo, pre_payload, tool_call_gate

from chock import vendors
from chock.compile.emitters.in_agent_tool_call import glob_matcher
from chock.hooks.in_agent_install import WIRED_VENDORS, install_hooks, installed_policy_ids
from chock.validation.loading import schema_validator

TOOL_CALL_VENDORS = {"claude_code", "codex_cli", "cursor", "gemini_cli", "vscode_copilot"}
NO_EVIDENCE = {"antigravity", "devin", "grok", "tabnine", "windsurf"}


def _fragments(repo: Path) -> set[str]:
    compiled = repo / ".chock" / "compiled" / POLICY_ID
    return {
        p.name for surface in ("pre-tool-use", "agent-hooks") for p in (compiled / surface).glob("*") if p.is_file()
    }


def test_only_vendors_with_recorded_tool_vocabulary_are_credited() -> None:
    assert set(vendors.tool_call_vendors()) == TOOL_CALL_VENDORS
    assert NO_EVIDENCE.isdisjoint(vendors.tool_call_vendors())


def test_a_tool_call_policy_emits_fragments_only_for_those_vendors(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, tool_call_gate())
    names = _fragments(repo)
    assert {"pretooluse-toolcall.json", "cursor-tool-call-hooks.json", "codex_cli-tool-call-hooks.json"} <= names
    assert {"gemini_cli-tool-call-hooks.json", "tool-call-hooks.json", "tool-call-gate.json"} <= names
    assert not {n for n in names if any(v in n for v in NO_EVIDENCE)}, "no invented matcher for an unrecorded vendor"
    assert not {"posttooluse.json", "cursor-post-hooks.json"} & names, "a regex gate reads no session: no recorder"


def test_claude_entry_carries_an_anchored_matcher_for_the_globs(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, tool_call_gate())
    entry = json.loads((repo / ".chock/compiled" / POLICY_ID / "pre-tool-use/pretooluse-toolcall.json").read_text())
    assert entry["matcher"] == glob_matcher(["WebFetch", "mcp__*"]) == "^(?:WebFetch|mcp__.*)$"
    assert "--tool-call" in entry["hooks"][0]["command"]


def test_cursor_and_copilot_carry_no_matcher_and_the_runtime_filters(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, tool_call_gate())
    cursor = json.loads((repo / ".chock/compiled" / POLICY_ID / "pre-tool-use/cursor-tool-call-hooks.json").read_text())
    copilot = json.loads((repo / ".chock/compiled" / POLICY_ID / "agent-hooks/tool-call-hooks.json").read_text())
    assert "matcher" not in json.dumps(cursor) and "matcher" not in json.dumps(copilot)


def test_a_script_gate_hears_every_tool_and_gets_recorders(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, tool_call_gate(script=True), script=SCRIPT)
    compiled = repo / ".chock/compiled" / POLICY_ID / "pre-tool-use"
    assert "matcher" not in json.loads((compiled / "pretooluse-toolcall.json").read_text())
    assert {"posttooluse.json", "posttoolusefailure.json", "cursor-post-hooks.json"} <= _fragments(repo)
    gemini = json.loads((compiled / "gemini_cli-tool-call-hooks.json").read_text())["hooks"]
    assert set(gemini) == {"BeforeTool", "AfterTool"}


def test_installed_only_where_a_fragment_exists(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, tool_call_gate())
    for vendor in WIRED_VENDORS:
        install_hooks(repo, vendor)
    assert {v for v in WIRED_VENDORS if POLICY_ID in installed_policy_ids(repo, v)} == TOOL_CALL_VENDORS


def test_every_emitted_fragment_is_one_an_installer_reads(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, tool_call_gate(script=True), script=SCRIPT)
    for vendor in WIRED_VENDORS:
        install_hooks(repo, vendor)
    settings = json.loads((repo / ".claude" / "settings.json").read_text())["hooks"]
    assert {"PreToolUse", "PostToolUse", "PostToolUseFailure"} <= set(settings)
    cursor = json.loads((repo / ".cursor" / "hooks.json").read_text())["hooks"]
    assert {"preToolUse", "postToolUse", "postToolUseFailure"} <= set(cursor)
    copilot = json.loads((repo / ".github" / "hooks" / "chock.json").read_text())["hooks"]
    assert "--tool-call" in json.dumps(copilot["PreToolUse"])
    assert "PostToolUse" not in copilot, "Copilot's own hooks file has no witnessed PostToolUse"


# --- the installed hook refuses -------------------------------------------------------------------


def _blocked(proc) -> bool:
    return proc.returncode == 2 or '"deny"' in proc.stdout


def _run(repo: Path, tool: str, tool_input: dict, **kw):
    gate = ".chock/compiled/guard-tools/pre-tool-use/tool-call-gate.json"
    return fire(repo, ["--tool-call", gate], pre_payload(repo, tool, tool_input, **kw))


def test_content_regex_refuses_a_matching_call_and_lets_others_through(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, tool_call_gate())
    install_hooks(repo, "claude_code")
    bad = _run(repo, "mcp__Firecrawl__firecrawl_scrape", {"url": "https://evil.example/x"})
    assert _blocked(bad) and "tool call refused by policy" in bad.stderr + bad.stdout
    assert not _blocked(_run(repo, "mcp__Firecrawl__firecrawl_scrape", {"url": "https://ok.example"}))
    assert not _blocked(_run(repo, "Read", {"file_path": "evil.example"})), "a tool outside the globs is not judged"
    assert not _blocked(_run(repo, "WebFetchExtra", {"url": "https://evil.example"})), "globs are anchored"


def test_script_gate_receives_the_documented_payload_and_speaks_by_exit_code(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, tool_call_gate(script=True), script=SCRIPT)
    install_hooks(repo, "claude_code")
    allowed = _run(repo, "mcp__Firecrawl__firecrawl_scrape", {"url": "https://a.example/ok"})
    assert not _blocked(allowed)
    payload = json.loads((repo / "payload.json").read_text())
    assert payload["tool"] == "mcp__Firecrawl__firecrawl_scrape"
    assert payload["input"] == {"url": "https://a.example/ok"}
    assert payload["repo_root"] == str(repo)
    assert payload["session"]["id"] == "sess-1"
    assert payload["session"]["log_path"].endswith(".chock/state/sess-1.jsonl")
    blocked = _run(repo, "mcp__Firecrawl__firecrawl_scrape", {"url": "https://a.example/blocked"})
    assert _blocked(blocked) and "that URL is blocked here" in blocked.stderr + blocked.stdout
    crashed = _run(repo, "mcp__Firecrawl__firecrawl_scrape", {"url": "https://a.example/crash"})
    assert _blocked(crashed) and "exited 7" in crashed.stderr + crashed.stdout


def test_a_missing_compiled_gate_refuses_rather_than_allows(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, tool_call_gate())
    install_hooks(repo, "claude_code")
    gone = fire(
        repo,
        ["--tool-call", ".chock/compiled/nope/pre-tool-use/tool-call-gate.json"],
        pre_payload(repo, "WebFetch", {}),
    )
    assert _blocked(gone) and "missing" in gone.stderr + gone.stdout


def test_a_gate_without_the_event_does_not_run_at_tool_call(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, {**tool_call_gate(), "on": ["commit", "tool_call"]})
    assert "tool-call-gate.json" in _fragments(repo)
    repo2 = tmp_path / "other"
    repo2.mkdir()
    made = make_repo(repo2, {**tool_call_gate(), "on": ["commit"], "params": {"content_pattern": "x"}})
    assert "tool-call-gate.json" not in _fragments(made)


# --- validation -----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("gate", "message"),
    [
        ({"kind": "content_regex", "on": ["tool_call"], "params": {"content_pattern": "x"}}, "params.tools"),
        ({"kind": "dependency_allowlist", "on": ["tool_call"], "params": {}}, "tool_call is judged by"),
        ({"kind": "content_regex", "on": ["commit"], "params": {"content_pattern": "x", "tools": ["A"]}}, "no effect"),
    ],
)
def test_validation_refuses_a_misdeclared_tool_call(gate: dict, message: str) -> None:
    from chock.validation.checks_gate_shape import _validate_gate
    from chock.validation.report import Report

    report = Report()
    _validate_gate({"action": "block", "message": "m", **gate}, "ref", report, tool_use_allowed=True)
    assert any(message in f.message for f in report.errors), [f.message for f in report.errors]


def test_the_manifest_schema_accepts_tool_call_and_bounds_the_tool_globs() -> None:
    from chock.gate.schema import KIND_PARAM_SCHEMAS

    validator = schema_validator(KIND_PARAM_SCHEMAS["script"])
    assert not list(validator.iter_errors({"script": "j.py", "tools": ["mcp__*", "WebFetch"]}))
    assert list(validator.iter_errors({"script": "j.py", "tools": ["bad glob[1]"]})), "no bracket classes"
    assert list(validator.iter_errors({"script": "j.py", "tools": []}))


def test_glob_matcher_escapes_and_translates() -> None:
    assert glob_matcher(["a.b", "c?d", "e*"]) == r"^(?:a\.b|c.d|e.*)$"
