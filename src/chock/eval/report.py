"""Rendering eval results for a human and for a machine."""

from __future__ import annotations

import json
from typing import Any

from chock.eval.model import PolicyResult

MARK = {"pass": "PASS", "fail": "FAIL", "pending": "PEND", "skipped": "SKIP", "error": "ERR "}

_DETAIL_WIDTH = 68


def _trim(detail: str) -> str:
    return detail if len(detail) <= _DETAIL_WIDTH else detail[: _DETAIL_WIDTH - 1] + "…"


def render_text(policies: list[PolicyResult], verbose: bool = False) -> str:
    lines: list[str] = []
    for policy in policies:
        shown = [r for r in policy.results if verbose or r.outcome != "skipped"]
        if not shown and not verbose:
            continue
        lines.append(f"\n{policy.policy_id}  [{policy.mode}]")
        for result in shown:
            case = result.case
            lines.append(f"  {MARK[result.outcome]}  {case.id:<34} {case.provenance:<9} {_trim(result.detail)}")
        if policy.score is not None:
            lines.append(f"  score {policy.score:.2f}" + ("" if policy.attestable else "   (not attestable)"))

    totals: dict[str, int] = {}
    for policy in policies:
        for result in policy.results:
            totals[result.outcome] = totals.get(result.outcome, 0) + 1
    summary = ", ".join(f"{count} {name}" for name, count in sorted(totals.items())) or "no cases"
    lines.append(f"\n{len(policies)} policies: {summary}")

    pending = sum(p.count("pending") for p in policies)
    skipped = sum(p.count("skipped") for p in policies)
    if pending:
        lines.append(f"{pending} case(s) are placeholders and block attestation. Write them or delete them.")
    if skipped:
        lines.append(f"{skipped} case(s) have no executable form; they are agent-mode material (tier 3).")
    return "\n".join(lines)


def render_json(policies: list[PolicyResult]) -> str:
    payload: list[dict[str, Any]] = []
    for policy in policies:
        payload.append(
            {
                "policy_id": policy.policy_id,
                "mode": policy.mode,
                "score": policy.score,
                "attestable": policy.attestable,
                "cases": [
                    {
                        "id": r.case.id,
                        "category": r.case.category,
                        "provenance": r.case.provenance,
                        "signal": r.signal,
                        "outcome": r.outcome,
                        "detail": r.detail,
                    }
                    for r in policy.results
                ],
            }
        )
    return json.dumps(payload, indent=2, sort_keys=False)
