"""Chock module (auto-organized from the original monolith)."""

from __future__ import annotations

import re

DEPTH_MARKERS = [
    "## Advanced usage",
    "## Edge cases",
    "## Troubleshooting",
    "## Full API",
    "## Implementation details",
    "## Rationale",
    "## Background",
    "## Detailed design",
    "## Architecture",
    "## Migration guide",
    "## FAQ",
]

AGENT_SPECIFIC_KEYWORDS = [
    "claude code",
    "claude-code",
    "claude.md",
    "claude computer use",
    "cursorrules",
    "cursor rules",
    ".cursorrules",
    "copilot",
    "github copilot",
    "devin",
    "codex",
    "openai codex",
    "windsurf",
    "codium",
    "continue.dev",
    "aider",
]

AGENT_SPECIFIC_PATTERNS = [re.compile(r"\b" + re.escape(kw) + r"\b", re.IGNORECASE) for kw in AGENT_SPECIFIC_KEYWORDS]

INJECTION_PATTERNS = [
    r"ignore (previous|all|prior) instructions?",
    r"\bsystem prompt\b",
    r"<\|im_start\|>",
    r"<\|im_end\|>",
    r"<\|endoftext\|>",
    r"\[INST\]",
    r"\bDAN mode\b",
    r"\bdeveloper mode\b",
    r"\bjailbreak\b",
    r"\byou are now\b",
    r"\bact as (a|an|the) (different|new|another)\b",
]

_VERB_PREFIXES = frozenset(
    {
        "add",
        "allow",
        "apply",
        "audit",
        "block",
        "build",
        "check",
        "create",
        "deny",
        "enforce",
        "evaluate",
        "eval",
        "generate",
        "guard",
        "init",
        "install",
        "optimize",
        "parse",
        "post",
        "preflight",
        "prevent",
        "protect",
        "refuse",
        "review",
        "run",
        "scan",
        "summarize",
        "validate",
        "verify",
        "wire",
        "fetch",
        "filter",
        "format",
        "lint",
        "mine",
        "onboard",
        "open",
        "publish",
        "reject",
        "report",
        "resolve",
        "scaffold",
        "search",
        "test",
        "transform",
        "update",
        "upgrade",
    }
)

_INT3_GRANDFATHERED_IDS = frozenset(
    {
        "chock-init",
        "policy-init",
        "validate",
        "optimize",
        "eval",
        "yagni",
        "minimal-content",
        "pre-generated-scripts",
    }
)

_DETERMINISTIC_HEURISTIC_PATTERNS = [
    re.compile(r"\\b\(\?:|\(\?\w|\\[dws]\b|\\b\b|\[\^?"),  # regex-ish
    re.compile(r"\b(grep|awk|sed|find|jq|python -c|bash -c|sh -c|perl -e|ruby -e)\b"),  # shell commands
    re.compile(r"\b(?:re\.search|re\.match|re\.compile|re\.findall|regex)\b"),  # regex library calls
]
