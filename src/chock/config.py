"""Shared .chock/config.yaml reader and policy toggle state resolver."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from chock.compile.surfaces import SURFACE_AGENTS, Surface

CONFIG_DIR = ".chock"
CONFIG_NAME = "config.yaml"


def load_config(repo_root: Path | str) -> dict[str, Any]:
    """Safe-load .chock/config.yaml; return {} if missing."""
    path = Path(repo_root) / CONFIG_DIR / CONFIG_NAME
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def agents_from_config(repo_root: Path) -> list[str]:
    """The agent list a repo compiles for: configured, or every supported agent."""
    config = load_config(repo_root)
    configured = config.get("chock", {}).get("supported_agents")
    if not configured:
        return sorted(SURFACE_AGENTS)
    unknown = [a for a in configured if a not in SURFACE_AGENTS]
    if unknown:
        msg = (
            f".chock/config.yaml supported_agents: unknown agent(s): {', '.join(unknown)}"
            f" -- valid: {', '.join(sorted(SURFACE_AGENTS))}"
        )
        raise ValueError(msg)
    deduped: list[str] = []
    for name in configured:
        if name not in deduped:
            deduped.append(name)
    return deduped


def _policy_overrides(config: dict[str, Any]) -> dict[str, Any]:
    return config.get("policies", {}).get("overrides", {})


def _disabled_list(config: dict[str, Any]) -> set[str]:
    return set(config.get("policies", {}).get("disabled", []))


def policy_status(
    config: dict[str, Any],
    policy_id: str,
    manifest: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Resolve effective state for a policy from config + manifest."""
    manifest = manifest or {}
    disabled = _disabled_list(config)
    override = _policy_overrides(config).get(policy_id, {})
    mandatory = bool(manifest.get("mandatory", False))

    if policy_id in disabled:
        return {"state": "disabled", "targets": None, "mandatory": mandatory}

    targets = override.get("surfaces")
    if not targets and override.get("enforcement") == "advise":
        targets = [Surface.AMBIENT_RULE.value]
    if not targets:
        targets = [s.value for s in Surface]

    return {
        "state": "overridden" if override else "enabled",
        "targets": targets,
        "mandatory": mandatory,
    }


def set_disabled(repo_root: Path | str, policy_id: str, *, disabled: bool) -> None:
    """Add or remove a policy from policies.disabled; round-trip the config file."""
    path = Path(repo_root) / CONFIG_DIR / CONFIG_NAME
    config = load_config(repo_root) or {}
    policies = config.setdefault("policies", {})
    disabled_list = list(policies.setdefault("disabled", []))

    if disabled:
        if policy_id not in disabled_list:
            disabled_list.append(policy_id)
    else:
        disabled_list = [p for p in disabled_list if p != policy_id]

    policies["disabled"] = disabled_list
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(
            config,
            sort_keys=False,
            default_flow_style=None,
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
