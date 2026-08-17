"""Validate .chock/config.yaml policy toggle state against manifests."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from chock.config import load_config
from chock.manifest import CANONICAL_MANIFEST, ManifestSourceError, load_manifest
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
            report.add(Finding(str(manifest_path), "manifest_default", "warning", warning))
    return data


def _policy_manifests(repo_root: Path, report: Report) -> dict[str, dict[str, Any]]:
    manifests: dict[str, dict[str, Any]] = {}
    for pack_dir in discover_policy_dirs(repo_root):
        manifest = _load_manifest(pack_dir, report)
        policy_id = manifest.get("id") or pack_dir.name
        manifests[policy_id] = manifest
    return manifests


def check_policy_toggles(repo_root: Path, report: Report) -> None:
    """Check that policy toggles are consistent with manifest mandatory/unknown rules."""
    config = load_config(repo_root)
    policies = config.get("policies", {})
    disabled = set(policies.get("disabled", []))
    overrides = policies.get("overrides", {})
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
        if manifest.get("enforcement") == "block" and policy_id in SECURITY_BLOCK_GUARDS:
            if override.get("enforcement") == "advise" or override.get("surfaces") == ["ambient-rule"]:
                report.add(
                    Finding(
                        str(repo_root / ".chock" / "config.yaml"),
                        "policy_toggles",
                        "warning",
                        f"Block security guard {policy_id} is downgraded to advisory",
                    )
                )
