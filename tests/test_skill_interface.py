"""D1: optional interface.yaml contracts for skills."""

from __future__ import annotations

from pathlib import Path

import yaml

from chock.manifest import load_manifest


def _skill_md(front: dict[str, object]) -> str:
    body = front.pop("_body", "# Skill\n")
    front_yaml = yaml.safe_dump(front, default_flow_style=False, sort_keys=False, allow_unicode=True)
    return f"---\n{front_yaml}---\n\n{body}"


def test_interface_yaml_does_not_trip_ambiguity(tmp_path: Path) -> None:
    """SKILL.md plus interface.yaml is not ambiguous; interface keys merge into the manifest."""
    skill_dir = tmp_path / "interface-skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        _skill_md(
            {
                "name": "interface-skill",
                "description": "A skill with an interface contract.",
                "metadata": {
                    "chock": {
                        "provenance": {
                            "author": "a",
                            "source_repo": "https://example.com",
                            "license": "Apache-2.0",
                            "trust_tier": "community",
                        },
                        "security": {"content_instructions": "never-obey"},
                        "skill_type": "nl",
                        "effects": ["read_only"],
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    (skill_dir / "interface.yaml").write_text(
        yaml.safe_dump(
            {
                "input_schema": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {"request": {"type": "string", "description": "request"}},
                    "required": ["request"],
                },
                "output_schema": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "outcome": {
                            "type": "string",
                            "enum": ["success", "failure", "needs_handoff"],
                            "description": "outcome",
                        }
                    },
                    "required": ["outcome"],
                },
                "evaluation": {"test_suite_ref": "evals/suite.yaml"},
            },
            default_flow_style=False,
            sort_keys=False,
            allow_unicode=True,
        ),
        encoding="utf-8",
    )

    manifest, _ = load_manifest(skill_dir)
    assert "input_schema" in manifest
    assert "output_schema" in manifest
    assert "evaluation" in manifest


def test_malformed_interface_yaml_warns_and_continues(tmp_path: Path) -> None:
    """A malformed interface.yaml is reported as a warning and the skill still loads."""
    skill_dir = tmp_path / "bad-interface"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        _skill_md(
            {
                "name": "bad-interface",
                "description": "A skill with a broken interface file.",
                "metadata": {
                    "chock": {
                        "provenance": {
                            "author": "a",
                            "source_repo": "https://example.com",
                            "license": "Apache-2.0",
                            "trust_tier": "community",
                        },
                        "security": {"content_instructions": "never-obey"},
                        "skill_type": "nl",
                        "effects": ["read_only"],
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    (skill_dir / "interface.yaml").write_text("  : broken\n", encoding="utf-8")

    warnings: list[str] = []
    manifest, _ = load_manifest(skill_dir, warnings=warnings)
    assert manifest["id"] == "bad-interface"
    assert any("interface.yaml parse error" in w for w in warnings)
