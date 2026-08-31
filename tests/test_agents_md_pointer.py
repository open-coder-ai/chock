"""AGENTS.md pointer block tests."""

from __future__ import annotations

from pathlib import Path

import yaml

from chock.scaffold.agents_md import POINTER_BLOCK, update_agents_md


def test_pointer_is_constant_regardless_of_installed_policies(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "AGENTS.md").write_text("# repo\n\n## Rules\n", encoding="utf-8")

    for i in range(3):
        dir_ = repo / ".agents" / "policies" / f"p{i}"
        dir_.mkdir(parents=True)
        (dir_ / "manifest.yaml").write_text(
            yaml.safe_dump(
                {
                    "id": f"p{i}",
                    "artifact": "rule",
                    "enforcement": "advise",
                    "rule": {"text": f"p{i}"},
                    "provenance": {"license": "Apache-2.0", "trust_tier": "sandbox"},
                }
            ),
            encoding="utf-8",
        )

    update_agents_md(repo / "AGENTS.md")
    text = (repo / "AGENTS.md").read_text(encoding="utf-8")
    assert POINTER_BLOCK in text

    dir_ = repo / ".agents" / "policies" / "p3"
    dir_.mkdir()
    (dir_ / "manifest.yaml").write_text(
        yaml.safe_dump(
            {
                "id": "p3",
                "artifact": "rule",
                "enforcement": "advise",
                "rule": {"text": "p3"},
                "provenance": {"license": "Apache-2.0", "trust_tier": "sandbox"},
            }
        ),
        encoding="utf-8",
    )

    update_agents_md(repo / "AGENTS.md")
    text2 = (repo / "AGENTS.md").read_text(encoding="utf-8")
    assert text == text2


def test_content_outside_markers_survives_unchanged(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    original = "# repo\n\nPreamble stays.\n\n## Rules\n\n## Hooks\n\nHook text.\n"
    (repo / "AGENTS.md").write_text(original, encoding="utf-8")
    update_agents_md(repo / "AGENTS.md")
    text = (repo / "AGENTS.md").read_text(encoding="utf-8")
    assert "Preamble stays." in text
    assert "Hook text." in text


def test_migrating_legacy_blocks_removes_only_those_blocks(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    original = (
        "# repo\n\n## Rules\n\n"
        "<!-- chock:rules:start (compiled by chock — edit .agents/policies/yagni/) -->\n"
        "```\nold rule\n```\n"
        "<!-- chock:rules:end -->\n\n"
        "<!-- chock:rules:start (compiled by chock — edit .agents/policies/code-safety/) -->\n"
        "```\nother\n```\n"
        "<!-- chock:rules:end -->\n\n"
        "## Hard rules\n\nkeep me\n"
    )
    (repo / "AGENTS.md").write_text(original, encoding="utf-8")
    update_agents_md(repo / "AGENTS.md")
    text = (repo / "AGENTS.md").read_text(encoding="utf-8")
    assert "old rule" not in text
    assert "other" not in text
    assert "keep me" in text
    assert POINTER_BLOCK in text


def test_refresh_twice_yields_no_diff(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "AGENTS.md").write_text("# repo\n\n## Rules\n", encoding="utf-8")
    update_agents_md(repo / "AGENTS.md")
    first = (repo / "AGENTS.md").read_bytes()
    update_agents_md(repo / "AGENTS.md")
    second = (repo / "AGENTS.md").read_bytes()
    assert first == second
