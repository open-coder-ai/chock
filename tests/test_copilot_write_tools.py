"""Copilot CLI's file tools reach the write gate and the toggle-file guard before the write lands.

Copilot runs a plugin's Claude-format `PreToolUse` hooks with Claude's matcher semantics and sends
`tool_name` as the Claude name of its runtime tool, but `tool_input` keeps the runtime tool's own
arguments: `create` {path, file_text}, `edit` {path, old_str, new_str}, and `apply_patch` the patch
text, bare or under `input`. The witness run (org-plan witness/results/witness-copilot-2026-10-08.md)
saw neither the unpinned workflow nor the toggle-file write refused on write: the hooks fired but
found no file text to judge. Basis: docs.github.com/en/copilot/reference/hooks-reference, "Claude-format
matchers (PascalCase PreToolUse)", and the Copilot CLI 1.0.63 bundle, both read 2026-10-08.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from bundle_fixtures import MARKER
from guardrails_support import TOGGLE, build, outcomes, refused

from chock.gate import write_gate
from chock.install.package import client

#: The vendor's runtime-to-Claude tool names, as the hooks reference tabulates them.
CLAUDE_NAME = {"create": "Write", "edit": "Edit", "str_replace_editor": "Edit", "apply_patch": "Edit"}
WORKFLOW = ".github/workflows/w.yml"
BEFORE = "jobs: {}\n"


def _fires(matcher: str, runtime_tool: str) -> bool:
    """Copilot's rule for a `|` alternation: any token equals the runtime name or its Claude name."""
    tokens = matcher.split("|")
    return runtime_tool in tokens or CLAUDE_NAME[runtime_tool] in tokens


def _patch(path: str, text: str) -> str:
    body = "".join(f"+{line}\n" for line in text.splitlines())
    return f"*** Begin Patch\n*** Add File: {path}\n{body}*** End Patch"


def _tool_input(tool: str, path: Path, rel: str, text: str) -> Any:
    if tool == "create":
        return {"path": str(path), "file_text": text}
    if tool == "edit":
        return {"path": str(path), "old_str": BEFORE, "new_str": text}
    if tool == "str_replace_editor":
        return {"command": "create", "path": str(path), "file_text": text}
    return _patch(rel, text)


def _payload(repo: Path, tool: str, tool_input: Any) -> dict[str, Any]:
    return {
        "hook_event_name": "PreToolUse",
        "session_id": "s",
        "timestamp": "2026-10-08T00:00:00.000Z",
        "cwd": str(repo),
        "tool_name": CLAUDE_NAME[tool],
        "tool_input": tool_input,
    }


@pytest.fixture
def copilot(tmp_path: Path) -> tuple[Path, Path, list[str], Path]:
    """(plugin, repo, the PreToolUse commands a Copilot write tool fires, home): the demo bundle as `--client copilot` ships it."""
    plugin, repo, _ = build(tmp_path, client("copilot")["format"])
    (repo / WORKFLOW).parent.mkdir(parents=True)
    (repo / WORKFLOW).write_text(BEFORE, encoding="utf-8")
    (repo / TOGGLE).parent.mkdir(parents=True)
    (repo / TOGGLE).write_text(BEFORE, encoding="utf-8")
    home = tmp_path / "home"
    home.mkdir()
    doc = json.loads(next(plugin.rglob("hooks.json")).read_text(encoding="utf-8"))
    entries = doc["hooks"]["PreToolUse"]
    commands = [h["command"] for e in entries if _fires(e.get("matcher", ""), "create") for h in e["hooks"]]
    assert commands, "no PreToolUse entry fires for Copilot's create"
    return plugin, repo, commands, home


TOOLS = sorted(CLAUDE_NAME)


@pytest.mark.parametrize("tool", TOOLS)
def test_every_copilot_file_tool_fires_a_write_entry(copilot: tuple, tool: str) -> None:
    plugin, *_ = copilot
    entries = json.loads(next(plugin.rglob("hooks.json")).read_text(encoding="utf-8"))["hooks"]["PreToolUse"]
    assert sum(_fires(e.get("matcher", ""), tool) for e in entries) >= 2  # the member's gate and the protection


@pytest.mark.parametrize("tool", TOOLS)
def test_the_write_gate_refuses_what_a_copilot_tool_would_write(copilot: tuple, tool: str) -> None:
    plugin, repo, commands, home = copilot
    payload = _payload(repo, tool, _tool_input(tool, repo / WORKFLOW, WORKFLOW, f"{MARKER}\n"))
    assert any(refused(p) for p in outcomes(commands, plugin, repo, payload, home)), tool


@pytest.mark.parametrize("tool", TOOLS)
def test_the_protection_refuses_a_copilot_tool_writing_the_toggle_file(copilot: tuple, tool: str) -> None:
    plugin, repo, commands, home = copilot
    payload = _payload(repo, tool, _tool_input(tool, repo / TOGGLE, TOGGLE, "{}\n"))
    assert any(refused(p) for p in outcomes(commands, plugin, repo, payload, home)), tool


@pytest.mark.parametrize("tool", TOOLS)
def test_a_clean_copilot_write_passes(copilot: tuple, tool: str) -> None:
    plugin, repo, commands, home = copilot
    payload = _payload(repo, tool, _tool_input(tool, repo / WORKFLOW, WORKFLOW, "jobs: {ok: {}}\n"))
    assert not any(refused(p) for p in outcomes(commands, plugin, repo, payload, home)), tool


def _event(tool_input: Any) -> SimpleNamespace:
    return SimpleNamespace(event="pre_tool", path=None, content=None, raw={"tool_input": tool_input})


@pytest.mark.parametrize(
    "wrap", [lambda p: p, lambda p: {"input": p}, lambda p: {"patch": p}], ids=["bare", "input", "patch"]
)
def test_a_copilot_apply_patch_is_read_wherever_it_carries_the_patch(tmp_path: Path, wrap: Any) -> None:
    patch = _patch(WORKFLOW, "a\nb")
    assert write_gate.writes_from_event(_event(wrap(patch)), tmp_path) == {WORKFLOW: "a\nb\n"}


def test_a_create_is_judged_as_its_file_text() -> None:
    event = SimpleNamespace(event="pre_tool", path="x.txt", content=None, raw={"tool_input": {"file_text": "t"}})
    assert write_gate.writes_from_event(event) == {"x.txt": "t"}


def test_the_adapters_own_content_still_wins_over_file_text() -> None:
    event = SimpleNamespace(event="pre_tool", path="x.txt", content="c", raw={"tool_input": {"file_text": "t"}})
    assert write_gate.writes_from_event(event) == {"x.txt": "c"}
