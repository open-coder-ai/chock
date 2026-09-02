"""Gate shape checks: validate hook.gate specs."""

from __future__ import annotations

from typing import Any

from chock.gate.runner import KINDS
from chock.gate.schema import GATEWAY_ONLY_KINDS, KIND_PARAM_SCHEMAS
from chock.validation.loading import schema_validator
from chock.validation.report import Finding, Report

_CATEGORY = "manifest_gate_params"


def _validate_gate(gate: dict[str, Any], gate_ref: str, report: Report, *, tool_use_allowed: bool = False) -> None:
    """Validate a gate spec: kind is known and params match the kind schema."""
    kind = gate.get("kind")
    if not kind:
        report.add(Finding(gate_ref, _CATEGORY, "error", "gate is missing 'kind'"))
        return

    if kind not in KINDS and kind not in GATEWAY_ONLY_KINDS:
        report.add(Finding(gate_ref, _CATEGORY, "error", f"unknown gate kind: {kind!r}"))
        return

    events = gate.get("on") or []
    if kind in GATEWAY_ONLY_KINDS and any(e in ("commit", "push") for e in events):
        report.add(
            Finding(
                gate_ref,
                _CATEGORY,
                "error",
                f"{kind} has no commit/push runtime; it binds only at tool_use (mcp-gateway)",
            )
        )

    if not tool_use_allowed and any(e == "tool_use" for e in events):
        report.add(
            Finding(
                gate_ref,
                _CATEGORY,
                "error",
                "tool_use is only allowed in hook.gate, not in gate.yaml",
            )
        )

    param_schema = KIND_PARAM_SCHEMAS.get(kind)
    if param_schema is not None:
        params = gate.get("params") or {}
        validator = schema_validator(param_schema)
        for exc in sorted(validator.iter_errors(params), key=lambda e: e.path):
            path_str = "/".join(str(p) for p in exc.path)
            report.add(
                Finding(
                    f"{gate_ref} (params)",
                    _CATEGORY,
                    "error",
                    f"{exc.message} at {path_str}",
                )
            )
