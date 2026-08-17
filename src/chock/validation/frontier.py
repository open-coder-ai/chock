"""Chock module (auto-organized from the original monolith)."""

from __future__ import annotations

import datetime
import json
import re
from pathlib import Path
from typing import Any

from chock.validation.loading import (
    count_lines,
)
from chock.validation.report import Finding, Report


def load_frontier_standard(agent: str) -> dict[str, Any] | None:
    # Map mode names to standard file names.
    standard_map = {
        "claude": "claude-code",
        "codex": "agentskills",  # Codex uses Agent Skills
        "cursor": "agentskills",
        "copilot": "agentskills",
        "devin": "agentskills",
        "openai": "agentskills",
    }
    standard_name = standard_map.get(agent, agent)
    standards_dir = Path(__file__).parent / "frontier_standards"
    path = standards_dir / f"{standard_name}.json"
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("extends"):
        base = load_frontier_standard(data["extends"])
        if base:
            merged = base.copy()
            # Deep merge to avoid shallow update bugs once nested keys overlap.
            for key, value in data.items():
                if isinstance(value, dict) and key in merged and isinstance(merged[key], dict):
                    merged[key] = {**merged[key], **value}
                else:
                    merged[key] = value
            return merged
    return data


def check_frontier_mode(
    artifact_dir: Path, manifest: dict[str, Any], artifact_type: str, mode: str, report: Report
) -> None:
    """Apply frontier-model-specific requirements when --mode frontier-<agent> is set."""
    agent = mode.replace("frontier-", "")
    standard = load_frontier_standard(agent)
    if not standard:
        report.add(
            Finding(
                str(artifact_dir),
                "frontier",
                "warning",
                f"No frontier standard found for {agent}. Run python -m chock.validation.frontier_ingest --agent {agent}.",
            )
        )
        return

    # FRS-1: warn if the frontier standard is older than 90 days.
    fetched_at = standard.get("fetched_at")
    if fetched_at:
        try:
            fetched = datetime.datetime.fromisoformat(fetched_at)
            age_days = (datetime.datetime.now(datetime.timezone.utc) - fetched).days
            if age_days > 90:
                report.add(
                    Finding(
                        str(artifact_dir),
                        "frontier_staleness",
                        "warning",
                        f"Frontier standard for {agent} was last fetched {age_days} days ago; run ingest.py to refresh (FRS-1).",
                    )
                )
        except Exception:
            pass  # staleness notice is advisory; a malformed fetched_at must not fail validation

    if artifact_type == "skill":
        desc_std = standard.get("skill_description", {})
        if "max_length" in desc_std:
            limit = desc_std["max_length"]
            description = manifest.get("description", "")
            if len(description) > limit:
                report.add(
                    Finding(
                        str(artifact_dir),
                        "frontier_description",
                        "error",
                        f"{mode} description exceeds {limit} chars (found {len(description)}).",
                    )
                )

        body_std = standard.get("skill_md_body", {})
        skill_md = artifact_dir / "SKILL.md"
        if skill_md.exists() and "max_lines" in body_std:
            lines = count_lines(skill_md)
            if lines > body_std["max_lines"]:
                report.add(
                    Finding(
                        str(skill_md),
                        "frontier_body",
                        "error",
                        f"{mode} SKILL.md body exceeds {body_std['max_lines']} lines (found {lines}).",
                    )
                )

        name_std = standard.get("skill_name", {})
        if "pattern" in name_std:
            pattern = name_std["pattern"]
            name = manifest.get("id", "")
            if name and not re.match(pattern, name):
                report.add(
                    Finding(
                        str(artifact_dir),
                        "frontier_name",
                        "error",
                        f"{mode} skill id '{name}' does not match required pattern '{pattern}'.",
                    )
                )

        compat_std = standard.get("compatibility", {})
        if "max_length" in compat_std:
            compat = manifest.get("compatibility", "")
            if len(compat) > compat_std["max_length"]:
                report.add(
                    Finding(
                        str(artifact_dir),
                        "frontier_compatibility",
                        "error",
                        f"{mode} compatibility exceeds {compat_std['max_length']} chars.",
                    )
                )
