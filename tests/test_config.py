"""Tests for .chock/config.yaml reader and policy toggle resolver."""

from pathlib import Path

import yaml

from chock.config import load_config, policy_status, set_disabled


def test_load_config_missing_returns_empty(tmp_path: Path) -> None:
    """A repo without config.yaml yields an empty config."""
    assert load_config(tmp_path) == {}


def test_policy_status_enabled_by_default() -> None:
    """With no config, a policy is enabled and targets all surfaces."""
    status = policy_status({}, "scan-secrets")
    assert status["state"] == "enabled"
    assert status["targets"] is not None
    assert "git-hook" in status["targets"]
    assert status["mandatory"] is False


def test_policy_status_disabled() -> None:
    """A policy in disabled is disabled and has no targets."""
    config = {"policies": {"disabled": ["block-no-verify"], "overrides": {}}}
    status = policy_status(config, "block-no-verify")
    assert status["state"] == "disabled"
    assert status["targets"] is None


def test_policy_status_overridden_targets() -> None:
    """overrides.<id>.surfaces maps to compile targets."""
    config = {"policies": {"disabled": [], "overrides": {"scan-secrets": {"surfaces": ["ambient-rule"]}}}}
    status = policy_status(config, "scan-secrets")
    assert status["state"] == "overridden"
    assert status["targets"] == ["ambient-rule"]


def test_policy_status_enforce_advise_shorthand() -> None:
    """overrides.<id>.enforcement: advise is shorthand for surfaces: [ambient-rule]."""
    config = {"policies": {"disabled": [], "overrides": {"scan-secrets": {"enforcement": "advise"}}}}
    status = policy_status(config, "scan-secrets")
    assert status["state"] == "overridden"
    assert status["targets"] == ["ambient-rule"]


def test_policy_status_mandatory_from_manifest() -> None:
    """mandatory is read from the manifest."""
    status = policy_status({}, "scan-secrets", {"mandatory": True})
    assert status["mandatory"] is True


def test_set_disabled_round_trips_without_clobbering_defaults(tmp_path: Path) -> None:
    """set_disabled preserves the existing chock defaults block."""
    config_path = tmp_path / ".chock" / "config.yaml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        "chock:\n"
        "  version: '0.0.1'\n"
        "  supported_agents: [claude, cursor]\n"
        "  defaults:\n"
        "    verification_command: 'npm test'\n"
        "policies:\n"
        "  disabled: []\n"
        "  overrides: {}\n",
        encoding="utf-8",
    )

    set_disabled(tmp_path, "block-no-verify", True)

    after = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert after["policies"]["disabled"] == ["block-no-verify"]
    assert after["chock"]["defaults"]["verification_command"] == "npm test"


def test_set_disabled_can_enable(tmp_path: Path) -> None:
    """set_disabled with disabled=False removes the policy from the list."""
    config_path = tmp_path / ".chock" / "config.yaml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        "policies:\n  disabled: [block-no-verify]\n  overrides: {}\n",
        encoding="utf-8",
    )

    set_disabled(tmp_path, "block-no-verify", False)

    after = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert after["policies"]["disabled"] == []
