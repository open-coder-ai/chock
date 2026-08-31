"""The installed skill tree is generated from the shipped one, never hand-maintained."""

from __future__ import annotations

from pathlib import Path

from chock.scaffold.skills import (
    AUTHORING_SKILLS,
    differences,
    install_skills,
    installed_root,
    installed_shipped_ids,
    main,
    shipped_root,
)

ROOT = Path(__file__).resolve().parents[1]
DEAD_CONFIG_KEYS = ["verification_command", "immutable_paths", "context_budget", "file_read_budget"]


def test_this_repo_installs_the_skills_it_ships() -> None:
    """The dogfooding claim, checked rather than assumed."""
    assert not differences(ROOT), "run `chock install-skills .`"


def test_there_are_skills_to_compare() -> None:
    """Guard the guard: `differences` over an empty installed tree is empty, so it passes."""
    assert len(installed_shipped_ids(ROOT)) >= len(AUTHORING_SKILLS)


def test_the_installed_template_uses_the_placeholder_syntax_init_expands() -> None:
    """`init` calls `.format()` on this file: `{{agents}}` renders as the literal `{agents}`."""
    text = (installed_root(ROOT) / "chock-init" / "assets" / "templates" / ".chock" / "config.yaml").read_text(
        encoding="utf-8"
    )
    assert "{agents}" in text
    assert "{{agents}}" not in text


def test_the_installed_template_does_not_advertise_deleted_config_keys() -> None:
    """A key nothing resolves teaches adopters the whole config file is decorative."""
    text = (installed_root(ROOT) / "chock-init" / "assets" / "templates" / ".chock" / "config.yaml").read_text(
        encoding="utf-8"
    )
    keys = {line.strip().split(":")[0] for line in text.splitlines() if not line.strip().startswith("#")}
    assert not keys & set(DEAD_CONFIG_KEYS), keys & set(DEAD_CONFIG_KEYS)


def _install(tmp_path: Path) -> Path:
    install_skills(tmp_path, skills=["policy-init", "validate", "chock-init"])
    return installed_root(tmp_path)


def test_an_edited_file_is_drift(tmp_path: Path) -> None:
    installed = _install(tmp_path)
    (installed / "policy-init" / "SKILL.md").write_text("tampered\n", encoding="utf-8")
    assert any(d.startswith("differs:") for d in differences(tmp_path))


def test_a_missing_file_is_drift(tmp_path: Path) -> None:
    installed = _install(tmp_path)
    (installed / "policy-init" / "SKILL.md").unlink()
    assert any(d.startswith("missing:") for d in differences(tmp_path))


def test_a_file_no_longer_shipped_is_drift(tmp_path: Path) -> None:
    """A dead copy of every baseline policy lived under the installed init template."""
    installed = _install(tmp_path)
    (installed / "chock-init" / "assets" / "templates" / ".agents" / "policies" / "ghost").mkdir(parents=True)
    (installed / "chock-init" / "assets" / "templates" / ".agents" / "policies" / "ghost" / "manifest.yaml").write_text(
        "id: ghost\n", encoding="utf-8"
    )
    assert any(d.startswith("stale:") for d in differences(tmp_path))


def test_injected_schemas_are_not_drift(tmp_path: Path) -> None:
    """`validate/assets/manifest*.json` comes from the package, not the pack."""
    installed = _install(tmp_path)
    assert list((installed / "validate" / "assets").glob("manifest*.json")), "schemas were not injected"
    assert not differences(tmp_path)


def test_an_adopter_skill_is_not_reported(tmp_path: Path) -> None:
    """Business skills live in the same directory and are not ours to compare or replace."""
    _install(tmp_path)
    mine = installed_root(tmp_path) / "my-own-skill"
    mine.mkdir()
    (mine / "SKILL.md").write_text("mine\n", encoding="utf-8")

    assert not differences(tmp_path)
    install_skills(tmp_path)
    assert (mine / "SKILL.md").read_text(encoding="utf-8") == "mine\n"


def test_install_repairs_a_skill_outside_the_default_set(tmp_path: Path) -> None:
    """`chock-init` is not in AUTHORING_SKILLS, and its copy is the one that drifted."""
    installed = _install(tmp_path)
    assert "chock-init" not in AUTHORING_SKILLS
    (installed / "chock-init" / "SKILL.md").write_text("tampered\n", encoding="utf-8")

    install_skills(tmp_path)
    assert not differences(tmp_path)


def test_check_exits_non_zero_on_drift(tmp_path: Path) -> None:
    installed = _install(tmp_path)
    (installed / "policy-init" / "SKILL.md").write_text("tampered\n", encoding="utf-8")
    assert main([str(tmp_path), "--check"]) == 1
    assert main([str(tmp_path)]) == 0, "install should fix what --check reported"
    assert main([str(tmp_path), "--check"]) == 0


def test_check_writes_nothing(tmp_path: Path) -> None:
    installed = _install(tmp_path)
    tampered = installed / "policy-init" / "SKILL.md"
    tampered.write_text("tampered\n", encoding="utf-8")
    main([str(tmp_path), "--check"])
    assert tampered.read_text(encoding="utf-8") == "tampered\n"


def test_shipped_and_installed_are_different_trees() -> None:
    """Guard against a tautology: a check comparing a tree to itself can never fail."""
    assert shipped_root().resolve() != installed_root(ROOT).resolve()


def test_shipped_skill_metadata_is_a_flat_string_map() -> None:
    """Every shipped SKILL.md carries spec-conformant metadata: string keys, string values."""
    import yaml

    for skill_md in sorted(shipped_root().glob("*/SKILL.md")):
        metadata = yaml.safe_load(skill_md.read_text(encoding="utf-8").split("---")[1]).get("metadata") or {}
        offenders = {k: v for k, v in metadata.items() if not (isinstance(k, str) and isinstance(v, str))}
        assert not offenders, f"{skill_md.parent.name}: non-string metadata entries {offenders}"
