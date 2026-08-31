"""Emit the mcp-gateway surface: gate specs the MCP proxy evaluates per tool call."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from chock.compile.emitters.advisory import template_message
from chock.emit import write_generated_json

RUNTIME_KINDS = ("content_regex", "egress_allowlist")

BINDS = {
    "content_regex": "string-arguments",
    "egress_allowlist": "url-arguments",
}


def emit(policy_dir: Path, output_dir: Path, manifest: dict[str, Any]) -> list[Path]:
    """Emit gateway-gate.json when the policy's gate kind has a gateway runtime."""
    gate = (manifest.get("hook") or {}).get("gate") or {}
    kind = gate.get("kind")
    if kind not in RUNTIME_KINDS:
        return []
    if "tool_use" not in (gate.get("on") or []):
        return []

    params = gate.get("params") or {}
    spec = {
        "kind": kind,
        "binds": BINDS[kind],
        "action": gate.get("action", "block"),
        "message": template_message(str(gate.get("message", "")).strip(), params),
        "params": params,
    }
    dest = Path(output_dir) / "gateway-gate.json"
    write_generated_json(dest, spec)
    return [dest]
