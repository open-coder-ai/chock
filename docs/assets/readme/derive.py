#!/usr/bin/env python3
"""Derive data.json for the README panels. Each subcommand rewrites only its own keys.

derive.py catalog   <chock-catalog checkout> <its commit sha>
derive.py agentseam <agentseam checkout> <its commit sha>
derive.py repos     (the public repo list, from repos.json)
derive.py readme    (README.md's derive blocks, from data.json and chock's install and witness data)
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import yaml

TIER = {"enforced-at-commit": "commit", "best-effort": "in-agent", "advisory": "advisory"}
RANK = {"commit": 0, "in-agent": 1, "advisory": 2}
LEVELS = ("commit", "in-agent", "warn-or-ask")
GRADES = ("enforced", "enforceable", "best-effort", "detect", "none")
OUT = Path(__file__).with_name("data.json")
REPOS = Path(__file__).with_name("repos.json")
BLOCKS = Path(__file__).with_name("readme-blocks.json")
README = Path(__file__).resolve().parents[3] / "README.md"
BLOCK = re.compile(r"(<!-- derive:(?P<name>[a-z_]+) -->)(?P<body>.*?)(<!-- /derive:(?P=name) -->)", re.DOTALL)
UNTESTED_PREFIX = "Untested:"
DEPRECATED = "deprecated"
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


def derive_catalog(catalog: Path, sha: str) -> dict:
    listed = yaml.safe_load((catalog / "registry.yaml").read_text(encoding="utf-8"))["policies"]
    registry = [p for p in listed if p["status"] != DEPRECATED]
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
    return {
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


def derive_agentseam(checkout: Path, sha: str) -> dict:
    """Grade every (agent, event) cell with agentseam's own matrix.enforcement_level()."""
    sys.path.insert(0, str(checkout / "src"))
    from agentseam import contract, matrix  # noqa: PLC0415 -- importable only after the checkout joins sys.path

    agents = matrix.agents()
    grades = Counter(matrix.enforcement_level(a, e) for a in agents for e in contract.EVENTS)
    return {
        "agentseam": {
            "source": {"file": "agentseam matrix.enforcement_level()", "commit": sha},
            "agents": len(agents),
            "adapted_agents": len(matrix.adapted_agents()),
            "events": len(contract.EVENTS),
            "cells": sum(grades.values()),
            "grades": {g: grades[g] for g in GRADES},
        }
    }


def derive_repos() -> dict:
    return {"repos": json.loads(REPOS.read_text(encoding="utf-8"))}


def _fill(template: str, **subs: object) -> str:
    for key, value in subs.items():
        template = template.replace(f"__{key}__", str(value))
    return template


def _either(names: list[str]) -> str:
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " or " + names[-1]


def _table(head: tuple[str, ...], align: tuple[str, ...], rows: list[tuple[object, ...]]) -> str:
    lines = ["| " + " | ".join(head) + " |", "| " + " | ".join(align) + " |"]
    lines += ["| " + " | ".join(str(c) for c in row) + " |" for row in rows]
    return "\n".join(lines)


def plugin_clients() -> tuple[list[str], list[str]]:
    """(tested, untested) display names of `chock install` clients; untested is its own "Untested:" warning."""
    import chock.install  # noqa: PLC0415 -- chock is needed only for the readme blocks

    root = Path(chock.install.__file__).parent / "data"
    clients = json.loads((root / "install.json").read_text(encoding="utf-8"))["clients"]
    rules = json.loads((root / "warnings.json").read_text(encoding="utf-8"))["rules"]
    untested = {
        c for r in rules if r["kind"] == "client" and r["says"].startswith(UNTESTED_PREFIX) for c in r["clients"]
    }
    names = [(cid, c["name"]) for cid, c in clients.items()]
    return [n for cid, n in names if cid not in untested], [n for cid, n in names if cid in untested]


def repo_agents() -> tuple[int, int, list[str]]:
    """(agents chock sync wires, those with a native hook, clients its repo hooks were witnessed in)."""
    from chock import evidence  # noqa: PLC0415
    from chock.compile.surfaces import SURFACE_AGENTS, Surface  # noqa: PLC0415
    from chock.hooks import sync_notes  # noqa: PLC0415

    native = sum(1 for s in SURFACE_AGENTS.values() if {Surface.PRE_TOOL_USE, Surface.AGENT_HOOKS} & set(s))
    seen = [w.client for w in evidence.witnesses() if w.surface in sync_notes._HOOK_SURFACES]
    return len(SURFACE_AGENTS), native, seen


def readme_blocks(data: dict) -> dict[str, str]:
    """Every derive block's body, keyed by name."""
    t = json.loads(BLOCKS.read_text(encoding="utf-8"))
    stamp = _fill(t["stamp"], SHA=data["source"]["commit"][:7])
    labels, tiers = data["claude_code_labels"], data["tiers"]
    subs = {
        "POLICIES": data["policies"],
        "COMMIT": tiers["commit"],
        "IN_AGENT": tiers["in-agent"],
        "ADVISORY": tiers["advisory"],
        "BLOCK": labels["block"],
        "ASK": labels["ask"],
        "WARN": labels["warn"],
        "ADVISE": labels["advise"],
        "EVAL_CASES": f"{data['eval_cases']:,}",
        "EVAL_EXECUTED": f"{data['eval_executed']:,}",
    }
    numbers = [(k, _fill(v, **subs)) for k, v in t["numbers"]]
    incidents = [(i["incident"], f"`{i['policy']}`", i["tier"], i["eval_cases"]) for i in data["incidents"]]
    repos = [
        (f"[{r['name']}](https://github.com/open-coder-ai/{r['name']})", f"{r['kind']}: {r['line']}")
        for r in data["repos"]
    ]
    tested, untested = plugin_clients()
    agents, native, seen = repo_agents()
    return {
        "numbers": f"\n{stamp}\n\n{_table(('Measure', 'Value'), (':---', '---:'), numbers)}\n",
        "incidents": f"\n{stamp}\n\n"
        + _table(("Class of flaw behind", "Policy", "Tier", "Eval cases"), (":---", ":---", ":---", "---:"), incidents)
        + "\n",
        "plugins": _fill(t["plugins"], TESTED=_either(tested), UNTESTED=_either(untested)),
        "repo_agents": _fill(t["repo_agents"], WITNESSED="; ".join(seen)),
        "faq_agents": _fill(t["faq_agents"], ALL=agents, NATIVE=native, TESTED_N=len(tested), UNTESTED_N=len(untested)),
        "repos": f"\n{_fill(t['repos'], COUNT=len(repos))}\n\n"
        + _table(("Repository", "What it is"), (":---", ":---"), repos)
        + "\n",
    }


def render_readme(text: str, data: dict) -> str:
    """`text` with every derive block's body rewritten; a block with no derivation is an error."""
    bodies = readme_blocks(data)
    return BLOCK.sub(lambda m: m.group(1) + bodies[m.group("name")] + m.group(4), text)


def main(argv: list[str]) -> None:
    data = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
    if argv[0] == "catalog":
        data.update(derive_catalog(Path(argv[1]), argv[2]))
    elif argv[0] == "agentseam":
        data.update(derive_agentseam(Path(argv[1]), argv[2]))
    elif argv[0] == "readme":
        README.write_text(render_readme(README.read_text(encoding="utf-8"), data), encoding="utf-8")
        return
    else:
        data.update(derive_repos())
    OUT.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    sys.stdout.write(json.dumps({k: v for k, v in data.items() if k not in {"incidents", "repos"}}, indent=2) + "\n")


if __name__ == "__main__":
    main(sys.argv[1:])
