"""Emit Claude managed-settings.json fragments for a policy."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from chock.emit import write_generated_json


def emit(policy_dir: Path, output_dir: Path, manifest: dict[str, Any]) -> list[Path]:
    """Write a managed-settings.json fragment reflecting the policy's controls."""
    policy_id = manifest.get("id", policy_dir.name)
    fragments: dict[str, Any] = {"deny": [], "ask": []}

    if policy_id == "protect-main-branch":
        fragments["deny"].append(
            {
                "type": "text",
                "pattern": r"commit.*\b(main|master)\b|push.*refs/heads/(main|master)",
                "message": "Direct writes to main/master are denied; use a feature branch and pull request.",
            }
        )
    elif policy_id == "scan-secrets":
        fragments["deny"].append(
            {
                "type": "file",
                "pattern": "\\.(env|pem|key|p12|pfx)$",
                "message": "Credential files are denied in the workspace.",
            }
        )
        fragments["deny"].append(
            {
                "type": "text",
                "pattern": "(?i)(AKIA[0-9A-Z]{16}|ghp_[a-zA-Z0-9]{36}|eyJ[A-Za-z0-9_-]*\\.[A-Za-z0-9_-]*\\.[A-Za-z0-9_-]*|-----BEGIN .* PRIVATE KEY-----)",
                "message": "Credential-like values are denied in generated or edited files.",
            }
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    dest = output_dir / "managed-settings.json"
    write_generated_json(dest, fragments)
    return [dest]
