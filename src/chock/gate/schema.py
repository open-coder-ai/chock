"""Per-kind param JSON-schemas. Framework-side only — NOT imported by the vendored runner."""

from __future__ import annotations

from chock.gate.runner import EXTRACTORS

SUPPORTED_MANIFESTS = sorted(EXTRACTORS)

#: Gate kind name -- shared with eval/derive.py, which cannot import this framework-side
#: module's sibling (the vendored, stdlib-only gate/runner/ package duplicates it independently).
DEPENDENCY_ALLOWLIST_KIND = "dependency_allowlist"

#: The in-agent event that gates a tool call by name (`params.tools`), and the kinds able to judge one:
#: a call carries no file and no branch, only a tool name and its input.
TOOL_CALL_EVENT = "tool_call"
TOOL_CALL_KINDS = ("content_regex", "script")
#: Kinds handed the session log; their hook logs every tool call, so the log is complete.
TOOL_CALL_SESSION_KINDS = ("script",)

#: `params.tools`: globs over tool names, `*` and `?` only, so a vendor matcher can say the same thing.
TOOLS_PARAM = {
    "type": "array",
    "minItems": 1,
    "items": {"type": "string", "pattern": r"^[A-Za-z0-9_.:/@*?-]+$"},
}

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
            "tools": TOOLS_PARAM,
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
    "test_integrity": {
        **_CLOSED_OBJECT,
        "required": ["test_path_regex", "assertion_pattern"],
        "properties": {
            "test_path_regex": {"type": "string", "minLength": 1},
            "assertion_pattern": {"type": "string", "minLength": 1},
            "dummy_assertion_pattern": {"type": "string"},
            "allowlist_pragma": {"type": "string"},
        },
    },
    "script": {
        **_CLOSED_OBJECT,
        "required": ["script"],
        "properties": {
            # A bare file name under the policy's own implementations/: no separator, so no
            # way out of that directory, and .py only, which the runner's own interpreter runs.
            "script": {"type": "string", "pattern": r"^[A-Za-z0-9._-]+\.py$"},
            "tools": TOOLS_PARAM,
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
