#!/usr/bin/env python3
"""Frontier-model standard ingestion for Chock."""

from __future__ import annotations

import argparse
import datetime
import json
import re
import sys
from pathlib import Path
from typing import Any

STANDARDS_DIR = Path(__file__).parent / "frontier_standards"

#: Agent Skills feature name for shell-command-in-frontmatter dynamic expansion.
_DYNAMIC_CONTEXT_INJECTION = "dynamic_context_injection"

SEEDS: dict[str, dict[str, Any]] = {
    "agentskills": {
        "source": "https://agentskills.io/specification.md",
        "description": "Agent Skills open standard",
        "skill_name": {
            "max_length": 64,
            "pattern": r"^[a-z0-9]+(-[a-z0-9]+)*$",
            "must_match_parent_dir": True,
            "no_leading_hyphen": True,
            "no_trailing_hyphen": True,
            "no_consecutive_hyphens": True,
        },
        "skill_description": {
            "max_length": 1024,
            "min_length": 1,
        },
        "compatibility": {
            "max_length": 500,
        },
        "skill_md_body": {
            "max_lines": 500,
            "max_tokens": 5000,
        },
        "references": {
            "one_level_deep_from_skill_md": True,
        },
        "directories": {
            "required": ["SKILL.md"],
            "optional": ["scripts/", "references/", "assets/"],
        },
    },
    "claude-code": {
        "source": "https://code.claude.com/docs/en/skills",
        "description": "Claude Code skills extension of Agent Skills",
        "skill_path": {
            "project": ".claude/skills/<skill-name>/SKILL.md",
            "personal": "~/.claude/skills/<skill-name>/SKILL.md",
            "commands": ".claude/commands/<command-name>.md",
        },
        "features": [
            "invocation_control",
            "subagent_execution",
            _DYNAMIC_CONTEXT_INJECTION,
        ],
        _DYNAMIC_CONTEXT_INJECTION: {
            "syntax": "!`command`",
            "allowed": True,
        },
        "extends": "agentskills",
    },
}


def fetch_url(url: str) -> str:
    """Best-effort HTTPS fetch. Falls back to empty string on failure."""
    if not url.startswith("https://"):
        print(f"WARN: refusing non-https fetch: {url}", file=sys.stderr)
        return ""
    try:
        import urllib.request

        with urllib.request.urlopen(url, timeout=30) as response:  # noqa: S310 -- https:// enforced above
            return response.read().decode("utf-8")
    except Exception as exc:  # noqa: BLE001 -- best-effort fetch, by contract: never raise, always return a string
        print(f"WARN: could not fetch {url}: {exc}", file=sys.stderr)
        return ""


def extract_number(text: str, patterns: list[str]) -> int | None:
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            try:
                return int(match.group(1))
            except (IndexError, ValueError):
                continue
    return None


def parse_agentskills(text: str) -> dict[str, Any]:
    data: dict[str, Any] = {
        "source": "https://agentskills.io/specification.md",
        "description": "Agent Skills open standard (fetched)",
    }

    name_max = extract_number(
        text,
        [
            r"`name`\s*.*Max\s+(\d+)\s+characters",
            r"Must be\s+(\d+)-\d+\s+characters",
        ],
    )
    if name_max:
        data.setdefault("skill_name", {})["max_length"] = name_max

    desc_max = extract_number(
        text,
        [
            r"`description`\s*.*Max\s+(\d+)\s+characters",
            r"Must be\s+\d+-(\d+)\s+characters",
        ],
    )
    if desc_max:
        data.setdefault("skill_description", {})["max_length"] = desc_max

    compat_max = extract_number(
        text,
        [
            r"`compatibility`\s*.*Max\s+(\d+)\s+characters",
            r"Must be\s+\d+-(\d+)\s+characters",
        ],
    )
    if compat_max:
        data.setdefault("compatibility", {})["max_length"] = compat_max

    body_lines = extract_number(
        text,
        [
            r"Keep your main\s+`SKILL\.md`\s+under\s+(\d+)\s+lines",
        ],
    )
    if body_lines:
        data.setdefault("skill_md_body", {})["max_lines"] = body_lines

    body_tokens = extract_number(
        text,
        [
            r"Instructions\s+\(?<?\s*(\d+)\s*tokens",
            r"less than\s+(\d+)\s+tokens",
        ],
    )
    if body_tokens:
        data.setdefault("skill_md_body", {})["max_tokens"] = body_tokens

    return data


def parse_claude_code(text: str) -> dict[str, Any]:
    data: dict[str, Any] = {
        "source": "https://code.claude.com/docs/en/skills",
        "description": "Claude Code skills (fetched)",
        "extends": "agentskills",
    }

    if ".claude/skills/" in text:
        data["skill_path"] = {
            "project": ".claude/skills/<skill-name>/SKILL.md",
            "personal": "~/.claude/skills/<skill-name>/SKILL.md",
            "commands": ".claude/commands/<command-name>.md",
        }

    if "!`" in text:
        data[_DYNAMIC_CONTEXT_INJECTION] = {
            "syntax": "!`command`",
            "allowed": True,
        }

    return data


def _merge_into_seed(seed: dict[str, Any], fetched: dict[str, Any]) -> dict[str, Any]:
    """Merge fetched data into the richer built-in seed without losing defaults."""
    merged = seed.copy()
    for key, value in fetched.items():
        if isinstance(value, dict) and key in merged and isinstance(merged[key], dict):
            merged[key] = _merge_into_seed(merged[key], value)
        else:
            merged[key] = value
    return merged


def ingest(agent: str, *, use_network: bool = True) -> dict[str, Any]:
    seed = SEEDS.get(agent, {})
    source = seed.get("source", "")
    if use_network and source:
        text = fetch_url(source)
        if text:
            if agent == "agentskills":
                return _merge_into_seed(seed, parse_agentskills(text))
            if agent == "claude-code":
                parsed = parse_claude_code(text)
                parsed["extends"] = "agentskills"
                return _merge_into_seed(seed, parsed)

    print(f"INFO: using built-in seed for {agent}", file=sys.stderr)
    return seed


def save_standard(agent: str, data: dict[str, Any]) -> Path:
    """Persist a frontier standard with a fetched_at timestamp."""
    STANDARDS_DIR.mkdir(parents=True, exist_ok=True)
    data["fetched_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    path = STANDARDS_DIR / f"{agent}.json"
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return path


def load_standard(agent: str) -> dict[str, Any] | None:
    path = STANDARDS_DIR / f"{agent}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Chock frontier standard ingestion")
    parser.add_argument("--agent", choices=list(SEEDS.keys()), help="Agent standard to ingest")
    parser.add_argument("--all", action="store_true", help="Ingest all configured standards")
    parser.add_argument("--offline", action="store_true", help="Use built-in seeds only")
    args = parser.parse_args(argv)

    agents = list(SEEDS.keys()) if args.all else [args.agent]
    if not args.agent and not args.all:
        parser.print_help()
        return 1

    for agent in agents:
        data = ingest(agent, use_network=not args.offline)
        path = save_standard(agent, data)
        print(f"Wrote {agent} standard to {path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
