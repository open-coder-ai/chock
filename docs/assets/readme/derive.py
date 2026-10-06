#!/usr/bin/env python3
"""Derive data.json for the README panels: derive.py <chock-catalog checkout> <its commit sha>."""

from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import yaml

TIER = {"enforced-at-commit": "commit", "best-effort": "in-agent", "advisory": "advisory"}
RANK = {"commit": 0, "in-agent": 1, "advisory": 2}
LEVELS = ("commit", "in-agent", "warn-or-ask")
ASI = [f"ASI{n:02d}" for n in range(1, 11)]
INCIDENTS = [
    ("Log4Shell (CVE-2021-44228)", "java-security"),
    ("Spring4Shell (CVE-2022-22965), Text4Shell (CVE-2022-42889)", "java-security"),
    ("Struts OGNL (CVE-2017-5638)", "java-security"),
    ("SSRF, then an over-broad cloud role", "block-wildcard-iam"),
    ("tj-actions moved tag (2025)", "pin-github-actions"),
    ("Codecov bash uploader (2021), curl piped to a shell", "block-curl-pipe-sh"),
    ("MCP server at @latest", "block-unpinned-agent-components"),
    ("Leaked keys", "scan-secrets"),
    ("Trojan Source (CVE-2021-42574)", "block-invisible-unicode"),
]


def slice_level(tier: str, note: str) -> str:
    """What the mapped slice does (from its manifest note), not what the policy's tier says."""
    verb = note.split(" ", 1)[0].lower()
    if tier == "advisory":
        return "advisory"
    if verb in {"warns", "asks"}:
        return "warn-or-ask"
    return tier


def tier_of(entry: dict) -> str:
    return TIER[entry["enforces"].split(" ")[0]]


def main(catalog: Path, sha: str, out: Path) -> None:
    registry = yaml.safe_load((catalog / "registry.yaml").read_text(encoding="utf-8"))["policies"]
    by_id = {p["id"]: p for p in registry}
    tiers = Counter(tier_of(p) for p in registry)
    claude = Counter(p["label"]["claude-code"]["keyword"] for p in registry)
    asi: dict[str, list[str]] = defaultdict(list)
    slices: dict[str, set[str]] = defaultdict(set)
    for manifest in sorted(catalog.glob("*/*/manifest.yaml")):
        data = yaml.safe_load(manifest.read_text(encoding="utf-8"))
        if data["id"] in by_id:
            for control in (data.get("compliance") or {}).get("owasp_asi") or []:
                key = control["control"] if isinstance(control, dict) else control
                asi[key].append(data["id"])
                if isinstance(control, dict):
                    slices[key].add(slice_level(tier_of(by_id[data["id"]]), control.get("note") or ""))
    level = {c: next((lv for lv in LEVELS if lv in slices[c]), "advisory") for c in ASI if asi[c]}
    data = {
        "source": {"file": "chock-catalog registry.yaml and */*/manifest.yaml", "commit": sha},
        "policies": len(registry),
        "tiers": {k: tiers[k] for k in RANK},
        "claude_code_labels": dict(claude),
        "eval_cases": sum(p["eval_cases"] for p in registry),
        "eval_executed": sum(p["eval_executed"] for p in registry),
        "asi": {
            "with_policy": len(level),
            "refused_at_commit": [c for c in ASI if level.get(c) == "commit"],
            "in_agent_only": [c for c in ASI if level.get(c) == "in-agent"],
            "warn_or_ask_only": [c for c in ASI if level.get(c) == "warn-or-ask"],
            "advisory_only": [c for c in ASI if level.get(c) == "advisory"],
            "fully_covered": 0,
        },
        "incidents": [
            {"incident": name, "policy": pid, "tier": tier_of(by_id[pid]), "eval_cases": by_id[pid]["eval_cases"]}
            for name, pid in INCIDENTS
        ],
    }
    out.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    sys.stdout.write(json.dumps({k: v for k, v in data.items() if k != "incidents"}, indent=2) + "\n")


if __name__ == "__main__":
    main(Path(sys.argv[1]), sys.argv[2], Path(__file__).with_name("data.json"))
