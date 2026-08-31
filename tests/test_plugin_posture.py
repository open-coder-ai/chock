"""Packaged claims match the package: the frontmatter side of the posture discipline."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from chock.plugin.claude import claude_plugin_files
from chock.plugin.copilot import copilot_plugin_files

GUARD_MANIFEST = {
    "id": "block-destructive-commands",
    "name": "Block Destructive Commands",
    "version": "0.0.1",
    "description": "Block rm -rf and friends before they run.",
    "artifact": "hook",
    "enforcement": "block",
}

RULE_MANIFEST = {
    "id": "code-safety",
    "name": "Code Safety Rule",
    "version": "0.0.1",
    "description": "Advisory rule with no gate.",
    "artifact": "rule",
    "enforcement": "advise",
    "rule": {"text": "never(commit): secrets|keys|tokens"},
}


@pytest.fixture
def policy(tmp_path: Path):
    def _make(manifest: dict, guard: bool = False) -> Path:
        pack = tmp_path / ".agents" / "policies" / manifest["id"]
        pack.mkdir(parents=True)
        (pack / "manifest.yaml").write_text(yaml.safe_dump(manifest), encoding="utf-8")
        if guard:
            impl = pack / "implementations"
            impl.mkdir()
            (impl / f"{manifest['id']}.sh").write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
        return pack

    return _make


def _frontmatter(skill: str) -> dict:
    return yaml.safe_load(skill.split("---")[1])["metadata"]


def test_claude_frontmatter_claim_matches_the_package(policy, tmp_path: Path) -> None:
    """A hooked Claude package's frontmatter names its hook; a hookless one says advisory."""
    guarded = _frontmatter(
        claude_plugin_files(policy(GUARD_MANIFEST, guard=True), GUARD_MANIFEST, tmp_path)[
            Path("skills/block-destructive-commands/SKILL.md")
        ]
    )
    bare = _frontmatter(
        claude_plugin_files(policy(RULE_MANIFEST), RULE_MANIFEST, tmp_path)[Path("skills/code-safety/SKILL.md")]
    )
    assert guarded["chock.hooks"] == "hooks/hooks.json"
    assert "chock.coverage_without_chock" not in guarded
    assert bare["chock.coverage_without_chock"] == "advisory"
    assert "chock.hooks" not in bare


def test_copilot_frontmatter_claim_matches_the_package(policy, tmp_path: Path) -> None:
    """Same discipline in the copilot layout, whose hook lives under com.github.copilot/."""
    guarded = _frontmatter(
        copilot_plugin_files(policy(GUARD_MANIFEST, guard=True), GUARD_MANIFEST, tmp_path)[
            Path("skills/block-destructive-commands/SKILL.md")
        ]
    )
    bare = _frontmatter(
        copilot_plugin_files(policy(RULE_MANIFEST), RULE_MANIFEST, tmp_path)[Path("skills/code-safety/SKILL.md")]
    )
    assert guarded["chock.hooks"] == "com.github.copilot/hooks/hooks.json"
    assert "chock.coverage_without_chock" not in guarded
    assert bare["chock.coverage_without_chock"] == "advisory"
    assert "chock.hooks" not in bare
    for meta in (guarded, bare):
        assert all(isinstance(k, str) and isinstance(v, str) for k, v in meta.items())
