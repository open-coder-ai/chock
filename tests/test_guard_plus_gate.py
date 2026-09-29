"""One policy, both halves: a shell guard for commands and a content gate for writes, on a rule."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
import yaml

from chock import vendors
from chock.compile.compiler import compile_policy
from chock.compile.emitters.advisory import advisory_lines
from chock.hooks.in_agent_install import agent_hooks_rel, install_hooks, installed_policy_ids
from chock.index.builder import build_entries
from chock.index.render import render_index
from chock.validation.engine import validate_artifact
from chock.validation.report import Report

POLICY_ID = "protect-config"
RULE_TEXT = "never(hand_edit): agent config\nregenerate_via(chock sync)\n"
GATE = {
    "kind": "content_regex",
    "on": ["commit", "tool_use"],
    "action": "block",
    "message": "agent config is regenerated, not hand-edited",
    "params": {"scan": "added_lines", "content_pattern": "HAND_EDITED"},
}
#: claude_code and cursor merge into their own config, codex_cli and gemini_cli through the generic
#: installer, vscode_copilot into chock's owned file: one vendor per install path.
VENDORS = ("claude_code", "cursor", "codex_cli", "gemini_cli", "vscode_copilot")


def _manifest(**over: object) -> dict:
    base = {
        "id": POLICY_ID,
        "name": "Protect Config",
        "version": "0.0.1",
        "description": "trigger: editing agent config. avoid: hand edits.",
        "artifact": "rule",
        "enforcement": "block",
        "rule": {"text": RULE_TEXT},
        "hook": {"gate": GATE},
        "provenance": {"author": "t"},
        "lifecycle": {"status": "draft"},
    }
    base.update(over)
    return base


def _policy(repo: Path, manifest: dict, *, guard: bool = True) -> Path:
    policy = repo / ".agents" / "policies" / POLICY_ID
    (policy / "implementations").mkdir(parents=True, exist_ok=True)
    (policy / "manifest.yaml").write_text(yaml.safe_dump(manifest), encoding="utf-8")
    if guard:
        (policy / "implementations" / f"{POLICY_ID}.sh").write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    return policy


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    compile_policy(_policy(root, _manifest()), output_root=root / ".chock" / "compiled", repo_root=root)
    return root


def _commands(node: object) -> list[str]:
    """Every `command` string under a vendor config, whatever shape the vendor nests it in."""
    if isinstance(node, dict):
        found = [v for k, v in node.items() if k in {"command", "bash"} and isinstance(v, str)]
        return found + [c for v in node.values() for c in _commands(v)]
    if isinstance(node, list):
        return [c for v in node for c in _commands(v)]
    return []


def _config_path(repo: Path, vendor: str) -> Path:
    return repo / (agent_hooks_rel() if vendor == "vscode_copilot" else vendors.config_path(vendor))


def test_the_compiled_tree_carries_both_fragments(repo: Path) -> None:
    pre = repo / ".chock" / "compiled" / POLICY_ID / "pre-tool-use"
    names = {p.name for p in pre.iterdir()}
    assert {"pretooluse.json", "pretooluse-write.json", "gate.json"} <= names
    assert {"cursor-hooks.json", "cursor-write-hooks.json"} <= names
    hooks = repo / ".chock" / "compiled" / POLICY_ID / "agent-hooks"
    assert {p.name for p in hooks.iterdir()} == {"agent-hooks.json", "gate.json", "gate-hooks.json"}


@pytest.mark.parametrize("vendor", VENDORS)
def test_every_installer_merges_the_guard_and_the_gate(repo: Path, vendor: str) -> None:
    assert install_hooks(repo, vendor)

    commands = _commands(json.loads(_config_path(repo, vendor).read_text(encoding="utf-8")))
    assert any("--guard" in c and f"{POLICY_ID}.sh" in c for c in commands), "the shell guard is installed"
    # The stop surface also installs a `--gate` entry, so name the write-path gate's own file.
    write_gate = "agent-hooks/gate.json" if vendor == "vscode_copilot" else "pre-tool-use/gate.json"
    assert any("--gate" in c and write_gate in c for c in commands), "the write-path content gate is installed"
    assert installed_policy_ids(repo, vendor) == {POLICY_ID}


@pytest.mark.parametrize("vendor", VENDORS)
def test_a_policy_missing_half_its_entries_is_not_installed(repo: Path, vendor: str) -> None:
    """Coverage credit needs every compiled entry present, not any one of them."""
    install_hooks(repo, vendor)
    path = _config_path(repo, vendor)
    text = path.read_text(encoding="utf-8")
    doc = json.loads(text)

    def drop_gate(node: object) -> object:
        if isinstance(node, dict):
            return {k: drop_gate(v) for k, v in node.items()}
        if isinstance(node, list):
            return [drop_gate(v) for v in node if not ("--gate" in json.dumps(v) and "/stop/" not in json.dumps(v))]
        return node

    path.write_text(json.dumps(drop_gate(doc)), encoding="utf-8")

    assert installed_policy_ids(repo, vendor) == set()


def test_the_rule_text_stays_the_ambient_line(repo: Path) -> None:
    policy = repo / ".agents" / "policies" / POLICY_ID
    assert advisory_lines(policy, _manifest(), repo) == ["never(hand_edit): agent config", "regenerate_via(chock sync)"]


def test_the_index_lists_a_rule_with_a_gate_as_a_rule(repo: Path) -> None:
    entries, _ = build_entries(repo)
    text = render_index(entries, 2000).main
    assert f"- **{POLICY_ID}**:\n  never(hand_edit): agent config" in text


def _errors(repo: Path, manifest: dict) -> list[str]:
    policy = _policy(repo, manifest)
    report = Report()
    validate_artifact("rule", policy, "agnostic", report, repo, registry_check=False)
    return [f"{f.check}: {f.message}" for f in report.errors]


def test_validation_accepts_a_rule_carrying_a_gate(repo: Path) -> None:
    assert not [e for e in _errors(repo, _manifest()) if e.startswith(("manifest_payload", "manifest_schema"))]


@pytest.mark.parametrize(
    "hook",
    [
        {"gate": GATE, "script": {"on": ["commit"]}},
        {},
        {"gate": {**GATE, "kind": "nonsense"}},
    ],
    ids=["gate-and-script", "empty-hook", "unknown-kind"],
)
def test_validation_still_rejects_a_malformed_hook(repo: Path, hook: dict) -> None:
    assert _errors(repo, _manifest(hook=hook))


def test_a_rule_still_may_not_carry_a_second_payload(repo: Path) -> None:
    errors = _errors(repo, _manifest(workflow={"steps": []}))
    assert any(e.startswith("manifest_payload") for e in errors)
