"""A client hook timeout fails OPEN, so every engine timer (ask a person, or deny) must fire before it."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from chock import vendors
from chock.compile.compiler import _load_manifest, compile_policy
from chock.compile.emitters import in_agent, in_agent_hooks
from chock.gate import budget, guard_runner, runtime_bundle, tool_call_gate, write_gate
from chock.gate.assemble import runner_source
from chock.gate.runner import script as runner_script
from chock.plugin.claude import claude_plugin_files
from chock.plugin.codex import codex_plugin_files
from chock.plugin.copilot import copilot_plugin_files
from chock.plugin.cursor import cursor_plugin_files
from chock.plugin.devin import devin_plugin_files

ENGINE_BUDGET = budget.ENGINE_BUDGET_SECONDS
TIMEOUT_KEYS = ("timeout", "timeoutSec")
#: Vendors whose documented hooks schema has no timeout field. Pinned here so adding one is a decision.
NO_TIMEOUT_KEY = {"windsurf"}
MS_VENDORS = {"gemini_cli", "tabnine"}
HOOK_SURFACES = {"pre-tool-use", "stop", "agent-hooks"}
GUARD, TOOLS = "guard-both", "guard-tools"
JUDGE = "import sys\nsys.exit(0)\n"


def _manifest(policy_id: str, gate: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": policy_id,
        "name": policy_id,
        "version": "0.0.1",
        "description": "d",
        "artifact": "hook",
        "enforcement": "block",
        "hook": {"gate": {"action": "block", "message": "refused", **gate}},
        "provenance": {"author": "t", "license": "Apache-2.0", "source_repo": "https://example.invalid/r"},
        "lifecycle": {"status": "draft"},
    }


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A repo with a shell guard plus a tool_use script gate, and a tool_call session gate, compiled as `chock sync` does."""
    root = tmp_path / "repo"
    specs = {
        GUARD: {"kind": "script", "on": ["tool_use"], "params": {"script": "judge.py"}},
        TOOLS: {"kind": "script", "on": ["tool_call"], "params": {"script": "judge.py", "tools": ["mcp__*"]}},
    }
    for policy_id, gate in specs.items():
        policy = root / ".agents" / "policies" / policy_id
        (policy / "implementations").mkdir(parents=True)
        (policy / "manifest.yaml").write_text(yaml.safe_dump(_manifest(policy_id, gate)), encoding="utf-8")
        (policy / "implementations" / "judge.py").write_text(JUDGE, encoding="utf-8")
    (root / ".agents/policies" / GUARD / "implementations" / f"{GUARD}.sh").write_text("exit 0\n", encoding="utf-8")
    for policy_id in specs:
        compile_policy(
            root / ".agents" / "policies" / policy_id,
            output_root=root / ".chock" / "compiled",
            repo_root=root,
        )
    return root


def _documents(repo: Path) -> dict[str, Any]:
    """Every hooks document any emitter writes for the repo, keyed by a label whose stem names its vendor."""
    docs: dict[str, Any] = {}
    compiled = repo / ".chock" / "compiled"
    for path in compiled.rglob("*.json"):
        surface = path.relative_to(compiled).parts[1]
        if surface in HOOK_SURFACES and path.name not in {"gate.json", "tool-call-gate.json"}:
            docs[f"compiled/{path.relative_to(compiled).as_posix()}"] = json.loads(path.read_text(encoding="utf-8"))
    for plugin_files in (
        claude_plugin_files,
        codex_plugin_files,
        copilot_plugin_files,
        cursor_plugin_files,
        devin_plugin_files,
    ):
        policy = repo / ".agents" / "policies" / GUARD
        files = plugin_files(policy, _load_manifest(policy), repo)
        for rel, text in files.items():
            if "hooks" in rel.as_posix() and rel.suffix == ".json":
                docs[f"plugin/{plugin_files.__name__}/{rel.as_posix()}"] = json.loads(text)
    return docs


def _vendor_of(label: str) -> str | None:
    """The vendor a document's file name belongs to, where the name carries one."""
    name = label.rsplit("/", 1)[-1]
    return next((v for v in sorted(vendors.in_agent_vendors(), key=len, reverse=True) if name.startswith(v)), None)


def _entries(node: Any):
    """Every hook entry (a dict naming a command) anywhere under `node`."""
    if isinstance(node, dict):
        if isinstance(node.get("command"), str) or isinstance(node.get("bash"), str):
            yield node
        for child in node.values():
            yield from _entries(child)
    elif isinstance(node, list):
        for child in node:
            yield from _entries(child)


def _seconds(label: str, entry: dict[str, Any], key: str) -> float:
    """`entry[key]` in seconds: a millisecond vendor's file is read in its own unit."""
    return entry[key] / 1000 if _vendor_of(label) in MS_VENDORS else entry[key]


def test_margin_covers_interpreter_startup() -> None:
    assert in_agent_hooks.TIMEOUT_SECONDS == ENGINE_BUDGET + in_agent_hooks.STARTUP_MARGIN_SECONDS
    assert in_agent_hooks.STARTUP_MARGIN_SECONDS > 0


def test_one_budget_feeds_every_engine_timer() -> None:
    assert runner_script._SCRIPT_TIMEOUT_SECONDS == ENGINE_BUDGET
    for module in (guard_runner, write_gate, tool_call_gate):
        assert not [n for n in vars(module) if n.endswith("_TIMEOUT_SECONDS") and n != "_BASH_PROBE_SECONDS"], module
    assert f"ENGINE_BUDGET_SECONDS = {ENGINE_BUDGET}\n" in runner_source()
    assert "_SCRIPT_TIMEOUT_SECONDS = ENGINE_BUDGET_SECONDS" in runner_source()
    for vendor in vendors.in_agent_vendors():
        rendered = runtime_bundle.render(vendor)
        assert rendered.count(f"ENGINE_BUDGET_SECONDS = {ENGINE_BUDGET}\n") == 1, vendor


def test_every_emitted_hook_entry_outlasts_the_engine_budget(repo: Path) -> None:
    docs = _documents(repo)
    assert len(docs) > 25, "the walk must reach every emitter, not a sample"
    for label, doc in docs.items():
        entries = list(_entries(doc))
        assert entries, label
        if _vendor_of(label) in NO_TIMEOUT_KEY:
            continue
        for entry in entries:
            keys = [k for k in TIMEOUT_KEYS if k in entry]
            assert keys, f"{label}: a hook entry with no timeout key runs on the client's own default"
            for key in keys:
                assert _seconds(label, entry, key) > ENGINE_BUDGET, (label, key)


def test_the_walk_sees_every_emitter(repo: Path) -> None:
    labels = " ".join(_documents(repo))
    for needle in (
        "pretooluse.json",
        "pretooluse-write.json",
        "cursor-hooks.json",
        "cursor-write-hooks.json",
        "agent-hooks.json",
        "gate-hooks.json",
        "tool-call-hooks.json",
        "stop/stop.json",
        "stop/vscode_copilot-hooks.json",
        "stop/gemini_cli-hooks.json",
        "gemini_cli-hooks.json",
        "windsurf-hooks.json",
        "claude_plugin_files",
        "codex_plugin_files",
        "copilot_plugin_files",
        "cursor_plugin_files",
        "devin_plugin_files",
    ):
        assert needle in labels, needle


def test_every_in_agent_vendor_emits_a_timeout_or_is_allow_listed(repo: Path) -> None:
    assert in_agent_hooks.NO_TIMEOUT_KEY_VENDORS == NO_TIMEOUT_KEY
    docs = _documents(repo)
    for vendor in vendors.in_agent_vendors():
        labels = [label for label in docs if _vendor_of(label) == vendor]
        if vendor in {"claude_code", "vscode_copilot"}:
            labels += [label for label in docs if label.endswith(("pretooluse.json", "agent-hooks.json"))]
        assert labels, vendor
        stamped = any(k in e for label in labels for e in _entries(docs[label]) for k in TIMEOUT_KEYS)
        assert stamped or vendor in in_agent_hooks.NO_TIMEOUT_KEY_VENDORS, vendor
        assert stamped != (vendor in in_agent_hooks.NO_TIMEOUT_KEY_VENDORS), f"{vendor} is allow-listed yet emits one"


def test_the_vendor_table_names_field_unit_and_source() -> None:
    for vendor, facts in in_agent_hooks.VENDOR_TIMEOUTS.items():
        assert facts["source"].startswith("https://"), vendor
        if facts["field"] is None:
            continue
        assert facts["unit"] in {"s", "ms"}, vendor
        assert (vendor in MS_VENDORS) == (facts["unit"] == "ms"), vendor
        assert in_agent_hooks.vendor_timeout(vendor) == (
            facts["field"],
            in_agent_hooks.TIMEOUT_SECONDS * (1000 if facts["unit"] == "ms" else 1),
        )
    generic = set(in_agent.GENERIC_VENDORS)
    assert generic == set(in_agent_hooks.VENDOR_TIMEOUTS), "every generic vendor is documented in the table"


@pytest.mark.parametrize("vendor", ["claude_code", "codex_cli", "devin", "vscode_copilot"])
def test_hooks_map_timeout_exceeds_engine_budget(vendor: str) -> None:
    doc = in_agent_hooks.hooks_map_file(vendor, "cmd")
    assert all(e["timeout"] > ENGINE_BUDGET for e in _entries(doc))


def test_copilot_timeouts_exceed_engine_budget() -> None:
    entry = in_agent.copilot_entry("cmd")
    assert entry["timeout"] > ENGINE_BUDGET
    assert entry["timeoutSec"] > ENGINE_BUDGET
