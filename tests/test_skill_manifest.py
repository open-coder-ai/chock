"""D1: skills resolve their manifest from SKILL.md frontmatter."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from chock.manifest import ManifestSourceError, load_manifest
from chock.validation import engine
from chock.validation.report import Report

MIN_SUITE = """suite:
  id: {id}-tests
  policy_id: {id}
  metrics:
    pass_rate:
      direction: higher_is_better
      threshold: 1.0
      weight: 1.0
  cases:
    - id: tc-001
      category: trigger
      prompt: test
      expect: block
    - id: tc-002
      category: negative_trigger
      prompt: test
      expect: allow
    - id: tc-003
      category: behavior
      prompt: test
      expect: allow
"""


def _skill_md(front: dict[str, object]) -> str:
    body = front.pop("_body", "# Skill\n")
    front_yaml = yaml.safe_dump(front, default_flow_style=False, sort_keys=False, allow_unicode=True)
    return f"---\n{front_yaml}---\n\n{body}"


def test_frontmatter_only_skill_loads_and_validates(tmp_path: Path) -> None:
    """A complete SKILL.md frontmatter resolves into a valid nl skill manifest."""
    skill_dir = tmp_path / "check-test"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        _skill_md(
            {
                "name": "check-test",
                "description": "A test skill.",
                "metadata": {
                    "chock": {
                        "version": "0.1.0",
                        "artifact": "skill",
                        "enforcement": "advise",
                        "provenance": {
                            "author": "a",
                            "source_repo": "https://example.com",
                            "license": "Apache-2.0",
                            "trust_tier": "community",
                        },
                        "lifecycle": {"status": "review"},
                        "security": {"content_instructions": "never-obey"},
                        "skill_type": "nl",
                        "effects": ["read_only"],
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    warnings: list[str] = []
    result = load_manifest(skill_dir, warnings=warnings)
    assert result is not None
    manifest, _ = result
    assert not warnings
    assert manifest["artifact"] == "skill"
    assert manifest["skill"]["skill_type"] == "nl"
    assert manifest["skill"]["effects"] == ["read_only"]

    (skill_dir / "evals").mkdir()
    (skill_dir / "evals" / "suite.yaml").write_text(MIN_SUITE.format(id=skill_dir.name), encoding="utf-8")

    report = Report()
    engine.validate_artifact("skill", skill_dir, "agnostic", report, tmp_path, registry_check=False)
    assert report.is_clean()


def test_metadata_chock_maps_to_fields(tmp_path: Path) -> None:
    """metadata.chock.* drives the projected manifest fields."""
    skill_dir = tmp_path / "my-skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        _skill_md(
            {
                "name": "my-skill",
                "description": "A skill.",
                "metadata": {
                    "chock": {
                        "version": "1.2.3",
                        "enforcement": "block",
                        "provenance": {
                            "author": "b",
                            "source_repo": "https://example.com",
                            "license": "MIT",
                            "trust_tier": "verified",
                        },
                        "lifecycle": {"status": "production"},
                        "security": {"content_instructions": "never-obey"},
                        "skill_type": "nl",
                        "effects": ["writes_workspace"],
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    manifest, _ = load_manifest(skill_dir)
    assert manifest["version"] == "1.2.3"
    assert manifest["enforcement"] == "block"
    assert manifest["provenance"]["trust_tier"] == "verified"
    assert manifest["skill"]["effects"] == ["writes_workspace"]


def test_dotted_metadata_keys_expand(tmp_path: Path) -> None:
    """Dotted metadata.chock.* keys expand into nested manifest structure."""
    skill_dir = tmp_path / "dotted-skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        _skill_md(
            {
                "name": "dotted-skill",
                "description": "A skill.",
                "metadata": {
                    "chock.version": "0.0.1",
                    "chock.provenance.trust_tier": "sandbox",
                    "chock.skill_type": "nl",
                    "chock.effects": ["read_only"],
                },
            }
        ),
        encoding="utf-8",
    )

    manifest, _ = load_manifest(skill_dir)
    assert manifest["version"] == "0.0.1"
    assert manifest["provenance"]["trust_tier"] == "sandbox"
    assert manifest["skill"]["skill_type"] == "nl"


def test_name_not_directory_warns_but_loads(tmp_path: Path) -> None:
    """A frontmatter name that differs from the directory name warns but still resolves."""
    skill_dir = tmp_path / "dir-name"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        _skill_md(
            {
                "name": "Display Name",
                "description": "A skill with a display name.",
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

    warnings: list[str] = []
    manifest, _ = load_manifest(skill_dir, warnings=warnings)
    assert manifest["id"] == "dir-name"
    assert manifest["name"] == "Display Name"
    assert any("does not match directory" in w for w in warnings)


def test_missing_description_raises(tmp_path: Path) -> None:
    """A SKILL.md without a description is rejected."""
    skill_dir = tmp_path / "bad-skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\nname: bad-skill\n---\n\n# Skill\n",
        encoding="utf-8",
    )

    with pytest.raises(ManifestSourceError, match="description is a required"):
        load_manifest(skill_dir)


def test_both_manifest_and_skill_md_raises(tmp_path: Path) -> None:
    """A directory with both manifest.yaml and SKILL.md is ambiguous."""
    skill_dir = tmp_path / "ambiguous"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\nname: ambiguous\ndescription: x\n---\n",
        encoding="utf-8",
    )
    (skill_dir / "manifest.yaml").write_text(
        "id: ambiguous\nname: ambiguous\ndescription: x\n",
        encoding="utf-8",
    )

    with pytest.raises(ManifestSourceError, match="both manifest.yaml and SKILL.md"):
        load_manifest(skill_dir)


def test_nested_manifest_does_not_error(tmp_path: Path) -> None:
    """Direct-children-only check: nested manifest.yaml files are ignored."""
    skill_dir = tmp_path / "chock-init"
    skill_dir.mkdir()
    nested = skill_dir / "assets" / "templates" / ".agents" / "policies" / "demo"
    nested.mkdir(parents=True)
    (nested / "manifest.yaml").write_text(
        "id: demo\nname: Demo\ndescription: x\n",
        encoding="utf-8",
    )
    (skill_dir / "SKILL.md").write_text(
        _skill_md(
            {
                "name": "chock-init",
                "description": "Onboard a repo.",
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
                        "effects": ["writes_workspace"],
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    manifest, path = load_manifest(skill_dir)
    assert path.name == "SKILL.md"
    assert manifest["skill"]["skill_type"] == "nl"


def test_vanilla_agentskills_skill_loads_with_defaults_and_validates_as_nl(tmp_path: Path) -> None:
    """A minimal agentskills.io-style skill (name + description only) gets safe defaults."""
    skill_dir = tmp_path / "check-vanilla"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        _skill_md(
            {
                "name": "check-vanilla",
                "description": "A third-party skill with no Chock metadata.",
            }
        ),
        encoding="utf-8",
    )

    warnings: list[str] = []
    manifest, _ = load_manifest(skill_dir, warnings=warnings)
    assert manifest["artifact"] == "skill"
    assert manifest["enforcement"] == "advise"
    assert manifest["provenance"]["trust_tier"] == "sandbox"
    assert manifest["skill"]["skill_type"] == "nl"
    assert manifest["skill"]["effects"] == ["none"]
    assert warnings

    (skill_dir / "evals").mkdir()
    (skill_dir / "evals" / "suite.yaml").write_text(MIN_SUITE.format(id=skill_dir.name), encoding="utf-8")

    report = Report()
    engine.validate_artifact("skill", skill_dir, "agnostic", report, tmp_path, registry_check=False)
    assert report.is_clean()
