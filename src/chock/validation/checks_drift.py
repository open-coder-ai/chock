"""Chock module (auto-organized from the original monolith)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from chock.validation.report import Finding, Report


def _staged_paths(root: Path) -> list[str] | None:
    """Repo-relative staged paths, or None when there is no index to read."""
    proc = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "-z"],
        cwd=root,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    )
    if proc.returncode != 0:
        return None
    return [p for p in proc.stdout.split("\0") if p]


def _drift_severity(root: Path, event: str | None, policy_dirs: list[Path]) -> tuple[str, str]:
    """Severity for a drift finding, and the prefix that explains a softened one."""
    if event != "commit":
        return "error", ""
    staged = _staged_paths(root)
    if staged is None:
        return "error", ""
    watched = [".chock/"] + [d.relative_to(root).as_posix() + "/" for d in policy_dirs]
    if any(p.startswith(tuple(watched)) for p in staged):
        return "error", ""
    return "warning", "Pre-existing drift; this commit does not touch it. "


def check_compiled_drift(root: Path, report: Report, event: str | None = None) -> None:
    """The compiled tree must still be what the manifests produce."""
    from chock.compile.compiler import _load_manifest
    from chock.config import agents_from_config as _agents_from_config
    from chock.policies import discover_policy_dirs
    from chock.scaffold.recompile import compiled_differences

    compiled_root = root / ".chock" / "compiled"

    uncompiled = set()
    policy_dirs = list(discover_policy_dirs(root))
    for pack_dir in policy_dirs:
        policy_id = _load_manifest(pack_dir).get("id") or pack_dir.name
        if not (compiled_root / policy_id).exists():
            uncompiled.add(policy_id)

    severity, preexisting = _drift_severity(root, event, policy_dirs)

    try:
        config_agents = _agents_from_config(root)
    except ValueError as exc:
        report.add(
            Finding(
                str(root / ".chock" / "config.yaml"),
                "compiled_drift",
                severity,
                f"{exc}. Compiled drift cannot be judged until the config names real agents.",
            )
        )
        return

    for difference in compiled_differences(root, config_agents):
        _, _, rel = difference.partition(": ")
        head = rel.split("/")[0]
        if head in uncompiled:
            continue
        if head == "coverage.json" and uncompiled:
            continue
        report.add(
            Finding(
                str(root / ".chock"),
                "compiled_drift",
                severity,
                f"{preexisting}Compiled artifact does not match its source ({difference}). "
                "This is what enforces, so it is out of step with the policy it claims to apply. "
                "Run 'chock sync --repo .' and commit the result.",
            )
        )


def check_plugin_drift(root: Path, report: Report, event: str | None = None) -> None:
    """Packaged Agent Plugins output must still be what the manifest produces."""
    from chock.compile.compiler import _load_manifest
    from chock.plugin.build import PluginNameError, plugin_differences
    from chock.policies import discover_policy_dirs

    policy_dirs = list(discover_policy_dirs(root))
    packaged = [d for d in policy_dirs if (d / "plugin.json").exists()]
    if not packaged:
        return

    severity, preexisting = _drift_severity(root, event, policy_dirs)

    for policy_dir in packaged:
        manifest = _load_manifest(policy_dir)
        if not manifest:
            continue
        try:
            differences = plugin_differences(policy_dir, manifest, root)
        except PluginNameError as exc:
            report.add(
                Finding(
                    str(policy_dir),
                    "plugin_drift",
                    "error",
                    f"Packaged as an Agent Plugin, but its id is not a legal plugin name ({exc}). "
                    "Rename the policy, or delete plugin.json and skills/ to stop publishing it.",
                )
            )
            continue
        for difference in differences:
            report.add(
                Finding(
                    str(policy_dir),
                    "plugin_drift",
                    severity,
                    f"{preexisting}Packaged Agent Plugins output does not match its manifest ({difference}). "
                    "This is what other clients read, so it publishes a policy that no longer exists. "
                    "Run 'chock plugin build --repo .' and commit the result.",
                )
            )


def check_registry_freshness(
    artifact_dir: Path, manifest: dict[str, Any], artifact_type: str, root: Path, report: Report
) -> None:
    """Detect stale or missing registry entries."""
    registry_file = root / ".chock" / "registry.json"
    if not registry_file.exists():
        report.add(
            Finding(
                str(artifact_dir),
                "registry_freshness",
                "warning",
                "No registry found. Run 'chock registry scan'.",
            )
        )
        return

    try:
        registry = json.loads(registry_file.read_text(encoding="utf-8"))
        registered = registry.get("entries", {})
    except (json.JSONDecodeError, OSError):
        report.add(Finding(str(registry_file), "registry_freshness", "error", "Registry file is unreadable."))
        return

    artifact_id = manifest.get("id", "")
    artifact_version = manifest.get("version", "")

    versions = registered.get(artifact_id, [])
    matching = [e for e in versions if e.get("version") == artifact_version and e.get("artifact") == artifact_type]
    if not matching:
        report.add(
            Finding(
                str(artifact_dir),
                "registry_freshness",
                "error",
                f"Registry is stale: {artifact_type} '{artifact_id}' v{artifact_version} not found. Run registry scan.",
            )
        )

    if artifact_id in registered:
        seen_types = {e.get("artifact") for e in registered[artifact_id]}
        if len(seen_types) > 1:
            report.add(
                Finding(
                    str(artifact_dir),
                    "registry_freshness",
                    "info",
                    f"ID '{artifact_id}' is registered as {', '.join(sorted(seen_types))}. Resolution now filters by artifact type.",
                )
            )
