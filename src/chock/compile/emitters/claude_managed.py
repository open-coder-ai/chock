"""Emit Claude managed-settings.json fragments for a policy."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from chock.emit import write_generated_json


def emit(policy_dir: Path, output_dir: Path, manifest: dict[str, Any]) -> list[Path]:
    """Write a managed-settings.json fragment reflecting the policy's controls."""
    policy_id = manifest.get("id", policy_dir.name)
    fragments: dict[str, Any] = {"deny": [], "ask": []}

    if policy_id == "scan-secrets":
        fragments["deny"].append(
            {
                "type": "file",
                "pattern": "\\.(env|pem|key|p12|pfx|jks|keystore)$",
                "message": "Credential files are denied in the workspace.",
            }
        )
        fragments["deny"].append(
            {
                "type": "text",
                "pattern": (
                    "(?i)(AKIA[0-9A-Z]{16}|ghp_[a-zA-Z0-9]{36}|xox[bpas]-[0-9A-Za-z-]{10,}"
                    "|(sk|rk)_live_[0-9A-Za-z]{16,}|sk-ant-[0-9A-Za-z_-]{20,}|AIza[0-9A-Za-z_-]{35}"
                    "|npm_[0-9A-Za-z]{36}|eyJ[A-Za-z0-9_-]*\\.[A-Za-z0-9_-]*\\.[A-Za-z0-9_-]*"
                    "|-----BEGIN .* PRIVATE KEY-----)"
                ),
                "message": "Credential-like values are denied in generated or edited files.",
            }
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    dest = output_dir / "managed-settings.json"
    write_generated_json(dest, fragments)
    return [dest]
