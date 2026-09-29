"""The `tool_call` fragments: PreToolUse gated by tool name, and the session-log recorders beside it.

Only vendors in `vendors.tool_call_vendors()` get an entry: those whose pre-tool hook records a
tool vocabulary (or, for Copilot, whose own hooks file was witnessed). The rest get nothing, and
their coverage says so. The runtime re-checks every glob itself, so a matcher is only a narrowing:
where a vendor's matcher semantics are unrecorded (Cursor, Copilot) none is written and the hook
answers every tool, over-gating rather than under-gating.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from chock import vendors
from chock.compile.emitters.advisory import repo_root_from_output
from chock.compile.emitters.in_agent_hooks import adapter_rel, copilot_entry, cursor_entry, hook_entry
from chock.emit import write_generated_json
from chock.gate.build import build_gate_json
from chock.gate.schema import TOOL_CALL_EVENT, TOOL_CALL_KINDS, TOOL_CALL_SESSION_KINDS
from chock.hooks.launch import hook_command

TOOL_CALL_GATE_FILE = "tool-call-gate.json"
TOOL_CALL_FLAG = "--tool-call"
RECORD_FLAG = "--record"

#: Fragment names, one per (vendor shape, event). The installers glob for exactly these.
CLAUDE_PRE, CLAUDE_POST, CLAUDE_FAILURE = "pretooluse-toolcall.json", "posttooluse.json", "posttoolusefailure.json"
CURSOR_PRE, CURSOR_POST, CURSOR_FAILURE = (
    "cursor-tool-call-hooks.json",
    "cursor-post-hooks.json",
    "cursor-postfailure-hooks.json",
)
COPILOT_FILE = "tool-call-hooks.json"
GENERIC_SUFFIX = "-tool-call-hooks.json"

PRE_SURFACE, AGENT_HOOKS_SURFACE = "pre-tool-use", "agent-hooks"


def tool_call_gate_spec(policy_dir: Path, repo_root: Path) -> dict[str, Any] | None:
    """The compiled gate this policy wants run per tool call, or None: no `tool_call` event, or a kind that cannot."""
    spec = build_gate_json(policy_dir, repo_root)
    if spec is None or TOOL_CALL_EVENT not in spec.get("on", []):
        return None
    return spec if spec.get("kind") in TOOL_CALL_KINDS else None


def records_session(spec: dict[str, Any]) -> bool:
    """Whether the gate reads the session log, and so needs every call logged, not only the matched ones."""
    return spec.get("kind") in TOOL_CALL_SESSION_KINDS


def glob_matcher(globs: list[str]) -> str:
    """One anchored regex over tool-name globs (`*` any run, `?` one character), as vendors' matchers read them."""
    parts = ["".join(".*" if c == "*" else "." if c == "?" else re.escape(c) for c in glob) for glob in globs]
    return "^(?:" + "|".join(parts) + ")$"


def _matcher(spec: dict[str, Any]) -> str | None:
    """No matcher when the gate records the session: it must see every call to log it."""
    return None if records_session(spec) else glob_matcher(list(spec.get("params", {}).get("tools", [])))


def _ref(policy_id: str, surface: str) -> str:
    return f".chock/compiled/{policy_id}/{surface}/{TOOL_CALL_GATE_FILE}"


def _commands(vendor: str, policy_id: str, surface: str) -> tuple[str, str]:
    """(the PreToolUse command, the record command) for `vendor`."""
    ref = _ref(policy_id, surface)
    return (
        hook_command(adapter_rel(vendor), TOOL_CALL_FLAG, ref),
        hook_command(adapter_rel(vendor), RECORD_FLAG, ref),
    )


def _write(output_dir: Path, name: str, doc: dict[str, Any], written: list[Path]) -> None:
    dest = output_dir / name
    write_generated_json(dest, doc)
    written.append(dest)


def _claude(output_dir: Path, policy_id: str, spec: dict[str, Any], written: list[Path]) -> None:
    pre, record = _commands("claude_code", policy_id, PRE_SURFACE)
    _write(output_dir, CLAUDE_PRE, hook_entry(pre, matcher=_matcher(spec)), written)
    if records_session(spec):
        _write(output_dir, CLAUDE_POST, hook_entry(record), written)
        _write(output_dir, CLAUDE_FAILURE, hook_entry(record), written)


def _cursor(output_dir: Path, policy_id: str, spec: dict[str, Any], written: list[Path]) -> None:
    pre, record = _commands("cursor", policy_id, PRE_SURFACE)
    _write(output_dir, CURSOR_PRE, {vendors.pre_tool_event("cursor"): [cursor_entry(pre, fail_closed=True)]}, written)
    if records_session(spec):
        post_event = vendors.wire_event("cursor", "post_tool")
        failure_event = vendors.tool_failure_event("cursor")
        _write(output_dir, CURSOR_POST, {post_event: [cursor_entry(record)]}, written)
        _write(output_dir, CURSOR_FAILURE, {failure_event: [cursor_entry(record)]}, written)


def _generic(vendor: str, output_dir: Path, policy_id: str, spec: dict[str, Any], written: list[Path]) -> None:
    """agentseam's own rendering: the PreToolUse gate and, for a session gate, the after-tool recorder."""
    pre, record = _commands(vendor, policy_id, PRE_SURFACE)
    doc = vendors.pre_tool_hook_config(vendor, pre, matcher=_matcher(spec))
    if records_session(spec):
        doc["hooks"] = {**doc["hooks"], **vendors.post_tool_hook_config(vendor, record)["hooks"]}
    _write(output_dir, f"{vendor}{GENERIC_SUFFIX}", doc, written)


def emit_pre_tool_use(policy_id: str, spec: dict[str, Any], output_dir: Path) -> list[Path]:
    """The pre-tool-use surface's tool_call fragments and the gate they run, for every vendor but Copilot."""
    written: list[Path] = []
    _write(output_dir, TOOL_CALL_GATE_FILE, spec, written)
    for vendor in vendors.tool_call_vendors():
        if vendor in vendors.AGENT_HOOKS_VENDORS:
            continue
        if vendor == "claude_code":
            _claude(output_dir, policy_id, spec, written)
        elif vendor == "cursor":
            _cursor(output_dir, policy_id, spec, written)
        else:
            _generic(vendor, output_dir, policy_id, spec, written)
    return written


def emit_agent_hooks(policy_id: str, spec: dict[str, Any], output_dir: Path) -> list[Path]:
    """Copilot's tool_call entry for chock's own hooks file. PostToolUse is not witnessed there: no recorder."""
    written: list[Path] = []
    _write(output_dir, TOOL_CALL_GATE_FILE, spec, written)
    pre, _record = _commands("vscode_copilot", policy_id, AGENT_HOOKS_SURFACE)
    doc = {vendors.pre_tool_event("vscode_copilot"): [copilot_entry(pre)]}
    _write(output_dir, COPILOT_FILE, doc, written)
    return written


def spec_for(policy_dir: Path, output_dir: Path) -> dict[str, Any] | None:
    return tool_call_gate_spec(policy_dir, repo_root_from_output(output_dir))
