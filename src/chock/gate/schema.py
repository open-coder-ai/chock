"""Per-kind param JSON-schemas. Framework-side only — NOT imported by the vendored runner.

The dependency import runs one way only: this module reads the runner's extractor table so
validation and runtime agree on which manifest formats are supported. The runner still
imports nothing from `chock`, which is what keeps it copy-portable.
"""

from __future__ import annotations

from chock.gate.runner import EXTRACTORS

SUPPORTED_MANIFESTS = sorted(EXTRACTORS)

KIND_PARAM_SCHEMAS: dict[str, dict] = {
    "content_regex": {
        "type": "object",
        "additionalProperties": False,
        "required": ["content_pattern"],
        "properties": {
            "scan": {"type": "string", "enum": ["added_lines", "staged_blob"]},
            "content_pattern": {"type": "string", "minLength": 1},
            "forbidden_path_regex": {"type": "string"},
            "allowlist_pragma": {"type": "string"},
            "diff_filter": {"type": "string"},
        },
    },
    "forbidden_ref": {
        "type": "object",
        "additionalProperties": False,
        "required": ["refs"],
        "properties": {
            "refs": {"type": "array", "minItems": 1, "items": {"type": "string"}},
            "config_key": {"type": "string"},
        },
    },
    "dependency_allowlist": {
        "type": "object",
        "additionalProperties": False,
        "required": ["manifests", "allowlist_file"],
        "properties": {
            # Constrained to the formats the runner can actually parse. Previously any
            # string was accepted, so `manifests: [go.mod]` validated cleanly and then did
            # nothing at runtime -- a policy claiming enforcement it did not provide. The
            # enum is derived from the runner so the two cannot drift apart.
            "manifests": {
                "type": "array",
                "minItems": 1,
                "items": {"type": "string", "enum": SUPPORTED_MANIFESTS},
            },
            "allowlist_file": {"type": "string"},
        },
    },
    # Gateway-only kind: evaluated by chock.gateway against MCP tool-call payloads, never
    # by the vendored git runner (KINDS below stays git-only; checks_gate_shape unions the
    # two sets for the known-kind check).
    "egress_allowlist": {
        "type": "object",
        "additionalProperties": False,
        "required": ["allowed_hosts"],
        "properties": {
            "allowed_hosts": {"type": "array", "minItems": 1, "items": {"type": "string", "minLength": 1}},
        },
    },
}

#: Kinds with no git-hook runtime: valid in a manifest, emitted only to the mcp-gateway
#: surface. Kept beside the schemas so a new gateway kind cannot be added without a
#: param schema.
GATEWAY_ONLY_KINDS = frozenset({"egress_allowlist"})
