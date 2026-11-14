"""Validate .chock/config.yaml policy toggle state against manifests."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from chock.compile.surface_kinds import Surface
from chock.config import load_config
from chock.manifest import CANONICAL_MANIFEST, MANIFEST_DEFAULT, ManifestSourceError, load_manifest
from chock.scaffold.recompile import discover_policy_dirs
from chock.validation.report import Finding, Report

SECURITY_BLOCK_GUARDS = {"scan-secrets", "protect-main-branch"}


def _load_manifest(pack_dir: Path, report: Report | None = None) -> dict[str, Any]:
    warnings: list[str] = []
    try:
        result = load_manifest(pack_dir, warnings=warnings)
    except (yaml.YAMLError, OSError, ManifestSourceError) as exc:
        if report is not None:
            manifest_path = pack_dir / CANONICAL_MANIFEST
            report.add(Finding(str(manifest_path), "manifest_parse", "error", str(exc)))
        return {}
    if result is None:
        return {}
    data, manifest_path = result
    if report is not None:
        for warning in warnings:
            report.add(Finding(str(manifest_path), MANIFEST_DEFAULT, "warning", warning))
    return data


def _policy_manifests(repo_root: Path, report: Report) -> dict[str, dict[str, Any]]:
    manifests: dict[str, dict[str, Any]] = {}
    for pack_dir in discover_policy_dirs(repo_root):
        manifest = _load_manifest(pack_dir, report)
        policy_id = manifest.get("id") or pack_dir.name
        manifests[policy_id] = manifest
    return manifests


def _check_override_shape(config_path: Path, policy_id: str, override: Any, report: Report) -> None:
    """An override that is not a mapping, or names a surface that does not exist, is a typo that enables nothing."""
    if not isinstance(override, dict):
        report.add(
            Finding(str(config_path), "policy_toggles", "error", f"policies.overrides.{policy_id}: must be a mapping")
        )
        return
    surfaces = override.get("surfaces")
    if surfaces is None:
        return
    known = {s.value for s in Surface}
    listed = [surfaces] if isinstance(surfaces, str) else surfaces if isinstance(surfaces, list) else None
    unknown = [str(s) for s in listed if s not in known] if listed is not None else None
    if listed is None or unknown:
        what = f"unknown surface(s): {', '.join(unknown)}" if unknown else "must be a list of surface names"
        report.add(
            Finding(
                str(config_path),
                "policy_toggles",
                "error",
                f"policies.overrides.{policy_id}.surfaces: {what}; known: {', '.join(sorted(known))}",
            )
        )


def _toggles(config: dict[str, Any], config_path: Path, report: Report) -> tuple[set[str], dict[str, Any]] | None:
    """(disabled, overrides) from the config, or None after reporting a block of the wrong shape."""
    policies = config.get("policies") or {}
    if not isinstance(policies, dict):
        report.add(Finding(str(config_path), "policy_toggles", "error", "policies: must be a mapping"))
        return None
    disabled = policies.get("disabled") or []
    overrides = policies.get("overrides") or {}
    for key, value, kind in (("disabled", disabled, list), ("overrides", overrides, dict)):
        if not isinstance(value, kind):
            report.add(
                Finding(str(config_path), "policy_toggles", "error", f"policies.{key}: must be a {kind.__name__}")
            )
            return None
    return {str(p) for p in disabled}, overrides


def check_policy_toggles(repo_root: Path, report: Report) -> None:
    """Check that policy toggles are consistent with manifest mandatory/unknown rules."""
    config_path = repo_root / ".chock" / "config.yaml"
    toggles = _toggles(load_config(repo_root), config_path, report)
    if toggles is None:
        return
    disabled, overrides = toggles
    manifests = _policy_manifests(repo_root, report)

    for policy_id in disabled:
        manifest = manifests.get(policy_id)
        if manifest is None:
            report.add(
                Finding(
                    str(repo_root / ".chock" / "config.yaml"),
                    "policy_toggles",
                    "warning",
                    f"Unknown policy id in policies.disabled: {policy_id}",
                )
            )
            continue
        if manifest.get("mandatory"):
            report.add(
                Finding(
                    str(repo_root / ".chock" / "config.yaml"),
                    "policy_toggles",
                    "error",
                    f"Mandatory policy {policy_id} is listed in policies.disabled",
                )
            )

    for policy_id, override in overrides.items():
        manifest = manifests.get(policy_id)
        if manifest is None:
            report.add(
                Finding(
                    str(repo_root / ".chock" / "config.yaml"),
                    "policy_toggles",
                    "warning",
                    f"Unknown policy id in policies.overrides: {policy_id}",
                )
            )
            continue
        _check_override_shape(config_path, policy_id, override, report)
        if not isinstance(override, dict):
            continue
        if (
            manifest.get("enforcement") == "block"
            and policy_id in SECURITY_BLOCK_GUARDS
            and (override.get("enforcement") == "advise" or override.get("surfaces") == ["ambient-rule"])
        ):
            report.add(
                Finding(
                    str(repo_root / ".chock" / "config.yaml"),
                    "policy_toggles",
                    "warning",
                    f"Block security guard {policy_id} is downgraded to advisory",
                )
            )
