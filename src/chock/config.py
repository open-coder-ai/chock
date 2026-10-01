"""Shared .chock/config.yaml reader and policy toggle state resolver."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from chock import yamlio
from chock.compile.surface_kinds import Surface
from chock.vendors import CHOCK_AGENT

CONFIG_DIR = ".chock"
CONFIG_NAME = "config.yaml"


def load_config(repo_root: Path | str) -> dict[str, Any]:
    """Safe-load .chock/config.yaml; return {} if missing."""
    path = Path(repo_root) / CONFIG_DIR / CONFIG_NAME
    if not path.exists():
        return {}
    return yamlio.safe_load(path.read_text(encoding="utf-8")) or {}


def agents_from_config(repo_root: Path) -> list[str]:
    """The agent list a repo compiles for: configured, or every supported agent."""
    config = load_config(repo_root)
    configured = config.get("chock", {}).get("supported_agents")
    if not configured:
        return sorted(CHOCK_AGENT)
    unknown = [a for a in configured if a not in CHOCK_AGENT]
    if unknown:
        msg = (
            f".chock/config.yaml supported_agents: unknown agent(s): {', '.join(unknown)}"
            f" -- valid: {', '.join(sorted(CHOCK_AGENT))}"
        )
        raise ValueError(msg)
    deduped: list[str] = []
    for name in configured:
        if name not in deduped:
            deduped.append(name)
    return deduped


_GUIDANCE_MCP_RE = re.compile(r"^guidance_mcp:[ \t]*(?P<rest>[^#\n]*)")


def guidance_mcp_from_text(text: str) -> bool:
    """Opt-in to registering `chock mcp` with clients: exactly one top-level `guidance_mcp: true` line.

    Read line by line like `rollout:`, never by a YAML parser; absent, repeated or anything else is off."""
    found = [m.group("rest") for m in map(_GUIDANCE_MCP_RE.match, text.splitlines()) if m]
    return len(found) == 1 and found[0].strip().strip("'\"") == "true"


def guidance_mcp_enabled(repo_root: Path | str) -> bool:
    """`guidance_mcp:` in the working tree's `.chock/config.yaml`; a missing, symlinked or unreadable file is off."""
    path = Path(repo_root) / CONFIG_DIR / CONFIG_NAME
    try:
        return not path.is_symlink() and guidance_mcp_from_text(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        return False


def _policies(config: dict[str, Any]) -> dict[str, Any]:
    """The `policies:` block, or empty when it is absent, null, or not a mapping."""
    policies = config.get("policies") if isinstance(config, dict) else None
    return policies if isinstance(policies, dict) else {}


def _policy_overrides(config: dict[str, Any]) -> dict[str, Any]:
    overrides = _policies(config).get("overrides")
    return {k: v for k, v in overrides.items() if isinstance(v, dict)} if isinstance(overrides, dict) else {}


def _disabled_list(config: dict[str, Any]) -> set[str]:
    disabled = _policies(config).get("disabled")
    if isinstance(disabled, str):
        return {disabled}
    return {str(p) for p in disabled} if isinstance(disabled, list) else set()


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

    # POL-1: the config cannot disable a mandatory policy; validate reports the dead entry.
    if policy_id in disabled and not mandatory:
        return {"state": "disabled", "targets": None, "mandatory": mandatory}

    targets = override.get("surfaces")
    if isinstance(targets, str):
        targets = [targets]
    if not isinstance(targets, list) or not all(isinstance(t, str) for t in targets):
        targets = None
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
