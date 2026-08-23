"""Emit the mcp-gateway surface: gate specs the MCP proxy evaluates per tool call.

Honest-scope rule (chock#32): only gate kinds the gateway runtime actually evaluates are
emitted here. `content_regex` binds against string arguments of MCP tool calls (the
write-content slice) and `egress_allowlist` against URL arguments. `forbidden_ref` and
`dependency_allowlist` are deliberately absent until the runtime evaluates them --
emitting a spec nothing enforces is the overclaim the credo forbids.

The emitted file changes what installed clients run only after P3c wires a client config
through the proxy; until then this surface is compiled output with no coverage credit
(see Surface.MCP_GATEWAY in compile/surfaces.py).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from chock.compile.emitters.advisory import template_message
from chock.emit import write_generated_json

#: Kinds the gateway runtime evaluates today. Extend ONLY together with an evaluator in
#: chock/gateway/gates.py -- tests assert the two stay in lockstep.
RUNTIME_KINDS = ("content_regex", "egress_allowlist")

#: What slice of MCP traffic each kind binds against; recorded in the emitted spec so the
#: proxy and the docs describe the same boundary.
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
    # Opt-in only: the gateway carries a gate ONLY when its author listed `tool_use` in
    # `on`. Auto-binding a commit-time content_regex to every MCP tool call would enforce
    # it with different semantics (line scan of arg strings, scan/forbidden_path_regex
    # ignored) than the author wrote -- a surprise the credo forbids. egress_allowlist has
    # no commit runtime, so its `on` is `[tool_use]` and it qualifies naturally.
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
