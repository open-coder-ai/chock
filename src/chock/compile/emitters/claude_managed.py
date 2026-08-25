"""Emit Claude managed-settings.json fragments for a policy."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from chock.emit import write_generated_json


def emit(policy_dir: Path, output_dir: Path, manifest: dict[str, Any]) -> list[Path]:
    """Write a managed-settings.json fragment reflecting the policy's controls.

    Managed-setting is a static deny/ask list; it cannot run code or read repo state. So it
    faithfully represents only controls that reduce to a path/text match at tool-call time,
    and it is a NON-CREDITED surface (coverage never counts it as enforced). We therefore
    emit a fragment only where a static match is honest, and leave it empty otherwise --
    an empty fragment is the truthful managed-setting for a control this surface cannot carry.
    """
    policy_id = manifest.get("id", policy_dir.name)
    fragments: dict[str, Any] = {"deny": [], "ask": []}

    # protect-main-branch enforces at commit/push time by RESOLVING the current branch
    # (forbidden_ref -> git rev-parse); a static managed-setting cannot read branch state, so
    # any command-text approximation either misses `git commit` on main (the branch name is
    # not in the command) or false-positives on "main" in a message. The honest managed-setting
    # for branch protection is therefore empty -- enforcement lives in its git-hook and ci-gate
    # surfaces, which do read branch state.
    if policy_id == "scan-secrets":
        # A best-effort in-session echo of the credential-file and high-confidence prefix
        # shapes the scan-secrets git-hook blocks; the git-hook (which scans the staged diff)
        # remains authoritative. Kept lookahead-free so it holds under any client's regex
        # engine; the file variants and unquoted-assignment patterns the hook adds are left to
        # the hook rather than approximated unsafely here.
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
