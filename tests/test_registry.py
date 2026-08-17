"""Tests for the Chock registry."""

import json

import chock.registry as _pkg


def _load_registry():
    return _pkg


registry = _load_registry()


def test_resolve_filters_by_artifact_type(tmp_path, monkeypatch):
    """Resolving an ID shared by multiple artifact types must return the requested type."""
    monkeypatch.chdir(tmp_path)
    entries = {
        "yagni": [
            registry.RegistryEntry(
                id="yagni",
                artifact="rule",
                version="0.1.0",
                name="YAGNI Rule",
                description="rule",
                path=".agents/policies/yagni",
                manifest="manifest.yaml",
                trust_tier="sandbox",
                lifecycle_status="draft",
            ),
            registry.RegistryEntry(
                id="yagni",
                artifact="skill",
                version="0.1.1",
                name="YAGNI Skill",
                description="skill",
                path=".agents/skills/eval",
                manifest="manifest.yaml",
                trust_tier="sandbox",
                lifecycle_status="draft",
            ),
        ]
    }
    registry.save_registry(entries)

    rule = registry.resolve("yagni", artifact_type="rule")
    assert rule is not None and rule.artifact == "rule"

    skill = registry.resolve("yagni", artifact_type="skill")
    assert skill is not None and skill.artifact == "skill"

    unscoped = registry.resolve("yagni")
    assert unscoped is not None and unscoped.version == "0.1.1"


def test_resolve_non_numeric_version(tmp_path, monkeypatch):
    """Non-numeric version components must not crash resolution."""
    monkeypatch.chdir(tmp_path)
    entries = {
        "x": [
            registry.RegistryEntry(
                id="x",
                artifact="skill",
                version="v0.1.0",
                name="X",
                description="x",
                path="skills/x",
                manifest="manifest.yaml",
                trust_tier="sandbox",
                lifecycle_status="draft",
            )
        ]
    }
    registry.save_registry(entries)
    entry = registry.resolve("x")
    assert entry is not None


def test_registry_stores_script_hashes(tmp_path, monkeypatch):
    """Registry scan computes sha256 hashes for skill scripts and hook implementations."""
    monkeypatch.chdir(tmp_path)
    skill_dir = tmp_path / "skills" / "test-skill"
    skill_dir.mkdir(parents=True)
    scripts_dir = skill_dir / "scripts"
    scripts_dir.mkdir()
    (skill_dir / "manifest.yaml").write_text(
        "id: test-skill\nartifact: skill\nversion: 0.1.0\nenforcement: verify\n"
        "skill:\n  skill_type: code\n  entry: SKILL.md\n  effects: [read_only]\n"
        "provenance:\n  author: a\n  created_at: '2026-01-01T00:00:00Z'\n  license: Apache-2.0\n"
        "  trust_tier: sandbox\nlifecycle:\n  status: draft\nsecurity:\n  content_instructions: never-obey\n",
        encoding="utf-8",
    )
    (scripts_dir / "run.py").write_text("print('ok')", encoding="utf-8")

    entries, _ = registry.scan()
    assert "test-skill" in entries
    entry = entries["test-skill"][0]
    assert entry.script_hashes == {"run.py": registry._hash_file(scripts_dir / "run.py")}

    registry.save_registry(entries)
    data = json.loads((tmp_path / ".chock" / "registry.json").read_text(encoding="utf-8"))
    assert data["version"] == registry.REGISTRY_FORMAT_VERSION
    assert data["entries"]["test-skill"][0]["script_hashes"] == entry.script_hashes
