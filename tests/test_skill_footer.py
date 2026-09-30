"""A SKILL.md footer says what `chock` compiles for that policy, not what its artifact type implies."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml

from chock.plugin.build import _keywords, advisory_note, build_skill
from chock.plugin.claude import claude_plugin_files
from chock.plugin.codex import codex_plugin_files
from chock.plugin.copilot import copilot_plugin_files
from chock.plugin.cursor import cursor_plugin_files
from chock.plugin.devin import devin_plugin_files

LEAD = "This skill is advisory: the client reading it has no mechanism to enforce it."
STAYS_ADVISORY = "stays advisory even when compiled"
SITE = "See https://github.com/open-coder-ai/chock"
POLICY_ID = "demo"


def _gate(on: list[str], **extra: Any) -> dict[str, Any]:
    params: dict[str, Any] = {"content_pattern": "FORBIDDEN"}
    if "tool_call" in on:
        params["tools"] = ["Bash"]
    return {"hook": {"gate": {"kind": "content_regex", "on": on, "message": "no", "params": params, **extra}}}


def _policy(tmp_path: Path, artifact: str, extra: dict[str, Any], *, files: tuple[str, ...] = ()) -> tuple[Path, dict]:
    manifest: dict[str, Any] = {"id": POLICY_ID, "name": "Demo", "description": "demo policy", "artifact": artifact}
    manifest.update(extra)
    pack = tmp_path / ".agents" / "policies" / POLICY_ID
    (pack / "implementations").mkdir(parents=True)
    (pack / "manifest.yaml").write_text(yaml.safe_dump(manifest), encoding="utf-8")
    for name in files:
        (pack / "implementations" / name).write_text("#!/usr/bin/env python3\n", encoding="utf-8")
    return pack, manifest


def _footer(tmp_path: Path, artifact: str, extra: dict[str, Any], *, files: tuple[str, ...] = ()) -> str:
    pack, manifest = _policy(tmp_path, artifact, extra, files=files)
    skill = build_skill(pack, manifest, tmp_path)
    assert skill.endswith(f"{advisory_note(pack, manifest)}\n")
    return skill.rsplit("```\n\n", 1)[1].strip()


def test_a_rule_with_nothing_to_compile_stays_advisory(tmp_path: Path) -> None:
    footer = _footer(tmp_path, "rule", {})
    assert footer == (
        f"{LEAD[:-1]}, and this policy stays advisory even when compiled by `chock` "
        f"-- it ships rule text, not a blocking hook. {SITE}"
    )


def test_a_rule_with_a_guard_can_refuse_a_shell_command(tmp_path: Path) -> None:
    footer = _footer(tmp_path, "rule", {}, files=(f"{POLICY_ID}.py",))
    assert footer == (
        f"{LEAD} The same policy compiled by `chock` can refuse an agent's shell command before it runs. {SITE}"
    )
    assert STAYS_ADVISORY not in footer


def test_a_rule_with_git_scripts_can_refuse_at_those_events(tmp_path: Path) -> None:
    footer = _footer(tmp_path, "rule", {"hook": {"script": {"on": ["push", "commit", "commit-msg"]}}})
    assert footer == (
        f"{LEAD} The same policy compiled by `chock` can refuse a change at commit, push and commit-msg. {SITE}"
    )
    assert STAYS_ADVISORY not in footer


def test_a_block_gate_on_commit_and_tool_use_blocks_at_both(tmp_path: Path) -> None:
    footer = _footer(tmp_path, "hook", _gate(["commit", "tool_use"]))
    assert footer == (
        f"{LEAD} The same policy compiled by `chock` blocks at commit, on an agent's file writes "
        f"and at turn end. {SITE}"
    )
    assert STAYS_ADVISORY not in footer
    assert "exits non-zero" not in footer


def test_a_rule_with_a_gate_is_not_called_advisory(tmp_path: Path) -> None:
    footer = _footer(tmp_path, "rule", _gate(["tool_use"]))
    assert footer == (
        f"{LEAD} The same policy compiled by `chock` blocks on an agent's file writes and at turn end. {SITE}"
    )


def test_an_ask_gate_asks(tmp_path: Path) -> None:
    footer = _footer(tmp_path, "rule", _gate(["commit"], action="ask"))
    assert footer == f"{LEAD} The same policy compiled by `chock` asks at commit. {SITE}"
    assert "blocks" not in footer


def test_a_tool_call_warn_gate_only_warns(tmp_path: Path) -> None:
    footer = _footer(tmp_path, "rule", _gate(["tool_call"], action="warn"))
    assert footer == f"{LEAD} The same policy compiled by `chock` warns on tool calls. {SITE}"
    for claim in (STAYS_ADVISORY, "exits non-zero", "blocks", "refuse"):
        assert claim not in footer


def test_a_hook_with_a_commit_gate_only_does_not_claim_tool_surfaces(tmp_path: Path) -> None:
    footer = _footer(tmp_path, "hook", _gate(["commit"]))
    assert footer == f"{LEAD} The same policy compiled by `chock` blocks at commit. {SITE}"
    assert "exits non-zero" not in footer
    assert "file writes" not in footer


def test_a_guard_and_a_git_script_share_one_refusal_clause(tmp_path: Path) -> None:
    footer = _footer(tmp_path, "rule", {"hook": {"script": {"on": ["commit-msg"]}}}, files=(f"{POLICY_ID}.py",))
    assert footer == (
        f"{LEAD} The same policy compiled by `chock` can refuse an agent's shell command before it runs "
        f"and a change at commit-msg. {SITE}"
    )


def test_a_guard_and_a_warn_gate_are_both_named(tmp_path: Path) -> None:
    footer = _footer(tmp_path, "rule", _gate(["tool_call"], action="warn"), files=(f"{POLICY_ID}.sh",))
    assert footer == (
        f"{LEAD} The same policy compiled by `chock` can refuse an agent's shell command before it runs; "
        f"warns on tool calls. {SITE}"
    )


VENDORS: dict[str, Callable[..., dict[Path, str]]] = {
    "claude": claude_plugin_files,
    "codex": codex_plugin_files,
    "copilot": copilot_plugin_files,
    "cursor": cursor_plugin_files,
    "devin": devin_plugin_files,
}


@pytest.mark.parametrize("vendor", sorted(VENDORS))
@pytest.mark.parametrize(
    ("extra", "files"),
    [({}, (f"{POLICY_ID}.py",)), (_gate(["commit", "tool_use"]), ())],
    ids=["guard", "tool_use gate"],
)
def test_every_vendor_still_swaps_the_generic_footer(
    tmp_path: Path, vendor: str, extra: dict[str, Any], files: tuple[str, ...]
) -> None:
    pack, manifest = _policy(tmp_path, "rule", extra, files=files)
    generic = advisory_note(pack, manifest)
    skills = [text for path, text in VENDORS[vendor](pack, manifest, tmp_path).items() if path.name == "SKILL.md"]
    assert len(skills) == 1
    assert generic not in skills[0]
    assert LEAD not in skills[0]
    assert skills[0].rstrip().endswith("https://github.com/open-coder-ai/chock")


def test_a_dict_shaped_compliance_entry_contributes_its_control_id() -> None:
    manifest = {"compliance": {"owasp_asi": [{"control": "ASI01", "coverage": "partial", "note": "n"}, "ASI02"]}}
    keywords = _keywords(manifest)
    assert "asi01" in keywords
    assert "asi02" in keywords
    assert not any("coverage" in word for word in keywords)
