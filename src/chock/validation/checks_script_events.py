"""A declared git-event script exists, and a script on disk is declared."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from chock.compile.emitters import GUARD_SUFFIXES, SCRIPT_EVENTS
from chock.manifest import CANONICAL_MANIFEST, resolve_manifest_path
from chock.validation.report import Finding, Report

_CATEGORY = "manifest_script_events"


def script_path(policy_dir: Path, policy_id: str, event: str) -> Path | None:
    """The script the hook would run for `event`, or None when the policy ships none."""
    impl = Path(policy_dir) / "implementations"
    for suffix in GUARD_SUFFIXES:
        candidate = impl / f"{policy_id}-{SCRIPT_EVENTS[event]}{suffix}"
        if candidate.exists():
            return candidate
    return None


def shipped_events(policy_dir: Path, policy_id: str) -> set[str]:
    """The events this policy ships a script for, whatever the manifest claims."""
    return {event for event in SCRIPT_EVENTS if script_path(policy_dir, policy_id, event)}


def check_script_events(artifact_dir: Path, manifest: dict[str, Any], _artifact_type: str, report: Report) -> None:
    """Pin `hook.script.on` to the scripts on disk, in both directions."""
    policy_id = str(manifest.get("id") or Path(artifact_dir).name)
    declared = set((manifest.get("hook") or {}).get("script", {}).get("on") or [])
    shipped = shipped_events(artifact_dir, policy_id)
    if not declared and not shipped:
        return

    ref = str(resolve_manifest_path(artifact_dir) or (artifact_dir / CANONICAL_MANIFEST))
    names = {e: f"implementations/{policy_id}-{seg}.{{sh,py}}" for e, seg in SCRIPT_EVENTS.items()}

    for event in sorted(declared - shipped):
        report.add(
            Finding(
                ref,
                _CATEGORY,
                "error",
                f"hook.script declares '{event}' but the policy ships no {names[event]} -- "
                "the compiler would wire a hook to a script that is not there",
            )
        )
    for event in sorted(shipped - declared):
        report.add(
            Finding(
                ref,
                _CATEGORY,
                "error",
                f"{names[event]} is shipped but hook.script does not declare '{event}' -- "
                "nothing wires it, so the policy enforces less than its directory suggests",
            )
        )
