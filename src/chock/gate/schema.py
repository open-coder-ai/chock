"""Per-kind param JSON-schemas. Framework-side only — NOT imported by the vendored runner."""

from __future__ import annotations

from chock.gate.runner import EXTRACTORS

SUPPORTED_MANIFESTS = sorted(EXTRACTORS)

#: Gate kind name -- shared with eval/derive.py, which cannot import this framework-side
#: module's sibling (the vendored, stdlib-only gate/runner.py duplicates it independently).
DEPENDENCY_ALLOWLIST_KIND = "dependency_allowlist"

#: Every param schema below is a closed object -- no undeclared keys.
_CLOSED_OBJECT = {"type": "object", "additionalProperties": False}

KIND_PARAM_SCHEMAS: dict[str, dict] = {
    "content_regex": {
        **_CLOSED_OBJECT,
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
        **_CLOSED_OBJECT,
        "required": ["refs"],
        "properties": {
            "refs": {"type": "array", "minItems": 1, "items": {"type": "string"}},
            "config_key": {"type": "string"},
        },
    },
    DEPENDENCY_ALLOWLIST_KIND: {
        **_CLOSED_OBJECT,
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
        **_CLOSED_OBJECT,
        "required": ["allowed_hosts"],
        "properties": {
            "allowed_hosts": {"type": "array", "minItems": 1, "items": {"type": "string", "minLength": 1}},
        },
    },
}

GATEWAY_ONLY_KINDS = frozenset({"egress_allowlist"})
