"""Per-kind param JSON-schemas. Framework-side only — NOT imported by the vendored runner."""

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
            "manifests": {
                "type": "array",
                "minItems": 1,
                "items": {"type": "string", "enum": SUPPORTED_MANIFESTS},
            },
            "allowlist_file": {"type": "string"},
        },
    },
    "egress_allowlist": {
        "type": "object",
        "additionalProperties": False,
        "required": ["allowed_hosts"],
        "properties": {
            "allowed_hosts": {"type": "array", "minItems": 1, "items": {"type": "string", "minLength": 1}},
        },
    },
}

GATEWAY_ONLY_KINDS = frozenset({"egress_allowlist"})
