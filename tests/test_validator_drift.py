"""Validator drift/repo-level checks: registry freshness, copies, ambient, release."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

import chock.validation as _pkg


def _load_validator():
    return _pkg


validator = _load_validator()


def test_registry_freshness_flags_stale_entry(tmp_path):
    """A stale registry missing the current artifact should be reported."""
    registry_dir = tmp_path / ".chock"
    registry_dir.mkdir()
    (registry_dir / "registry.json").write_text(json.dumps({"version": "1.0.0", "entries": {}}))

    artifact_dir = tmp_path / "test-skill"
    artifact_dir.mkdir()
    manifest = {
        "id": "test-skill",
        "version": "0.1.0",
        "artifact": "skill",
    }
    report = validator.Report()
    validator.check_registry_freshness(artifact_dir, manifest, "skill", tmp_path, report)
    assert any(f.check == "registry_freshness" for f in report.errors)


def test_dependencies_resolvable(tmp_path):
    """Declared skill dependencies must exist in the registry."""
    registry_dir = tmp_path / ".chock"
    registry_dir.mkdir()
    (registry_dir / "registry.json").write_text(
        json.dumps({"version": "1.0.0", "entries": {"known": [{"artifact": "skill", "version": "0.1.0"}]}})
    )

    skill_dir = tmp_path / "test-skill"
    skill_dir.mkdir()
    manifest = {
        "id": "test-skill",
        "dependencies": {"skills": [{"id": "missing"}]},
    }
    report = validator.Report()
    validator.check_dependencies_resolvable(skill_dir, manifest, "skill", tmp_path, report)
    assert any(f.check == "dependencies" and "missing" in f.message for f in report.errors)


def test_ambient_tier_requires_community_or_override(tmp_path):
    """Sandbox rules in ambient context require ambient_override or community tier."""
    rule_dir = tmp_path / "test-rule"
    rule_dir.mkdir()
    manifest = {
        "id": "test-rule",
        "artifact": "rule",
        "enforcement": "advise",
        "rule": {"text": "test: rule"},
        "provenance": {"trust_tier": "sandbox"},
    }
    report = validator.Report()
    validator.check_ambient_tier(rule_dir, manifest, "rule", report)
    assert any(f.check == "ambient_tier" and "SEC-5" in f.message for f in report.errors)

    manifest["ambient_override"] = True
    report = validator.Report()
    validator.check_ambient_tier(rule_dir, manifest, "rule", report)
    assert not any(f.check == "ambient_tier" for f in report.errors)

    manifest["provenance"]["trust_tier"] = "community"
    manifest.pop("ambient_override", None)
    report = validator.Report()
    validator.check_ambient_tier(rule_dir, manifest, "rule", report)
    assert not any(f.check == "ambient_tier" for f in report.errors)


def _write_index_and_agents(root: Path, index_text: str, agents_text: str) -> None:
    (root / ".agents" / "policies").mkdir(parents=True, exist_ok=True)
    if index_text:
        (root / ".agents" / "policies" / "INDEX.md").write_text(index_text, encoding="utf-8")
    (root / "AGENTS.md").write_text(agents_text, encoding="utf-8")


def test_index_freshness_and_pointer_are_validated(tmp_path):
    """AGENTS.md must have the canonical pointer and INDEX.md must be fresh."""
    from chock.scaffold.agents_md import POINTER_BLOCK

    rule_dir = tmp_path / ".agents" / "policies" / "test-rule"
    rule_dir.mkdir(parents=True)
    (rule_dir / "manifest.yaml").write_text(
        yaml.safe_dump(
            {
                "id": "test-rule",
                "artifact": "rule",
                "enforcement": "advise",
                "rule": {"text": "before_add: need.exists"},
                "provenance": {"trust_tier": "sandbox"},
            }
        ),
        encoding="utf-8",
    )

    _write_index_and_agents(tmp_path, "", f"# AGENTS\n\n## Rules\n\n{POINTER_BLOCK}\n")
    from chock.index.cli import cmd_refresh

    cmd_refresh(["--repo", str(tmp_path)])

    report = validator.Report()
    validator.check_ambient_rule_blocks(tmp_path, report)
    assert not any(f.check == "ambient_pointer" for f in report.warnings)
    assert not any(f.check == "index_freshness" for f in report.warnings)

    (tmp_path / ".agents" / "policies" / "INDEX.md").write_text("stale\n", encoding="utf-8")
    report = validator.Report()
    validator.check_ambient_rule_blocks(tmp_path, report)
    assert any(f.check == "index_freshness" for f in report.warnings)


def test_install_skills_places_schemas(tmp_path):
    """install-skills must inject the installed package's manifest schemas into the"""
    from chock.scaffold.skills import install_skills
    from chock.validation.loading import SCHEMA_DIR

    install_skills(tmp_path)
    installed_assets = tmp_path / ".agents" / "skills" / "validate" / "assets"
    assert installed_assets.exists()
    for can_path in sorted(SCHEMA_DIR.glob("manifest*.json")):
        copy_path = installed_assets / can_path.name
        assert copy_path.exists(), f"{can_path.name} was not injected"
        assert can_path.read_bytes() == copy_path.read_bytes(), f"{can_path.name} drifted from canonical"


def test_release_consistency(tmp_path):
    """VERSION, pyproject, and top CHANGELOG entry must agree."""
    validator = _load_validator()
    (tmp_path / "VERSION").write_text("1.2.3\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text('[project]\nversion = "1.2.3"\n', encoding="utf-8")
    (tmp_path / "CHANGELOG.md").write_text("# log\n\n## 1.2.3 — ok\n", encoding="utf-8")
    report = validator.Report()
    validator.check_release_consistency(tmp_path, report)
    assert not report.errors
    (tmp_path / "pyproject.toml").write_text('[project]\nversion = "1.2.4"\n', encoding="utf-8")
    report2 = validator.Report()
    validator.check_release_consistency(tmp_path, report2)
    assert any(f.check == "release_consistency" for f in report2.errors)


def test_release_consistency_reads_the_whole_pep440_version(tmp_path):
    """The version pattern must capture pre-release suffixes, not truncate them."""
    validator = _load_validator()

    (tmp_path / "pyproject.toml").write_text('[project]\nversion = "0.0.1a0"\n', encoding="utf-8")
    (tmp_path / "CHANGELOG.md").write_text("# log\n\n## 0.0.1a0 — pre-release\n", encoding="utf-8")
    report = validator.Report()
    validator.check_release_consistency(tmp_path, report)
    assert not report.errors, "a correctly matched pre-release must not report a mismatch"

    (tmp_path / "pyproject.toml").write_text('[project]\nversion = "0.0.1"\n', encoding="utf-8")
    report2 = validator.Report()
    validator.check_release_consistency(tmp_path, report2)
    assert any(f.check == "release_consistency" for f in report2.errors), (
        "0.0.1a0 in the CHANGELOG against 0.0.1 in pyproject is a mismatch and must fail"
    )


def test_index_token_budget(tmp_path):
    """INDEX.md that exceeds index.max_tokens produces a token-budget warning."""
    from chock.scaffold.agents_md import POINTER_BLOCK

    (tmp_path / ".agents" / "policies").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".agents" / "policies" / "INDEX.md").write_text("x" * 9000, encoding="utf-8")
    (tmp_path / "AGENTS.md").write_text(f"# AGENTS\n\n{POINTER_BLOCK}\n", encoding="utf-8")

    report = validator.Report()
    validator.check_ambient_token_budget(tmp_path, report)
    assert any(f.check == "token_budget" for f in report.warnings)


def test_no_schema_file_is_single_line():
    """Pretty-printed schema files must span multiple lines."""
    for p in validator.SCHEMA_DIR.glob("*.json"):
        text = p.read_text(encoding="utf-8")
        assert "\n" in text, f"{p.name} is a single-line schema; expected pretty-printed output"


def _copy_policies(tmp_path) -> list[str]:
    """Install this repo's policies into a scratch repo, the way an adopter copies them in."""
    import shutil

    from conftest import REPO_POLICIES

    dest = tmp_path / ".agents" / "policies"
    dest.mkdir(parents=True)
    ids = []
    for src in sorted(p for p in REPO_POLICIES.iterdir() if p.is_dir()):
        shutil.copytree(src, dest / src.name)
        ids.append(src.name)
    return ids


def test_installed_policies_resolve_from_a_fresh_install(tmp_path):
    """A repo with policies copied in must not warn about the policies it holds."""
    from chock.validation.checks_repo import _resolve_id

    installed = _copy_policies(tmp_path)
    assert installed, "precondition: policies were copied in"

    unresolved = [pid for pid in installed if not _resolve_id(tmp_path, pid)]
    assert not unresolved, f"policies installed but unresolvable: {unresolved}"


def test_policies_table_columns_fit_the_longest_value(tmp_path):
    """Fixed column widths misaligned every row after a long policy id."""
    ids = _copy_policies(tmp_path)
    assert max(len(i) for i in ids) > 24, "precondition: a policy id exceeds the old hard-coded 24-character column"


def test_a_policy_folder_validated_directly_is_the_policy_not_its_children(tmp_path):
    """`validate <policy-folder>` is the documented authoring loop, and it used to misfire."""
    import shutil

    from conftest import baseline_policy

    from chock.validation.loading import discover_artifacts

    policy = tmp_path / "injection-defense"
    shutil.copytree(baseline_policy("injection-defense"), policy)
    assert (policy / "evals" / "suite.yaml").exists(), "fixture must carry the eval suite"

    found = list(discover_artifacts(policy))
    assert found == [("rule", policy)]


def test_a_repo_root_still_discovers_its_trees(tmp_path):
    """The root-is-an-artifact shortcut must not swallow ordinary repo discovery."""
    import shutil

    from conftest import baseline_policy

    from chock.validation.loading import discover_artifacts

    policy = tmp_path / ".agents" / "policies" / "injection-defense"
    policy.parent.mkdir(parents=True)
    shutil.copytree(baseline_policy("injection-defense"), policy)

    found = list(discover_artifacts(tmp_path))
    assert ("rule", policy) in found
