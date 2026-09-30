#!/bin/sh
# fmt: off
"exec" "$(command -v python3 || command -v python)" "$0" "$@"
# fmt: on
# Refuse shell commands that write to agent-config or vendored enforcement paths; reads and `chock sync` pass.
# Best effort and coarse: a write must target a protected path (redirect, writer verb, in-place edit, git checkout/restore, PowerShell cmdlet).

import os
import re
import shlex
import sys

from chock_shellparse import commands, writes_files

MARKER = "chock: approved-config-change"
PROTECTED = (
    "AGENTS.md",
    "CLAUDE.md",
    "GEMINI.md",
    "copilot-instructions.md",
    ".cursorrules",
    ".windsurfrules",
    ".aider.conf.yml",
    ".claude/settings",
    ".mcp.json",
    ".chock/bin",
    ".chock/compiled",
    ".chock/dependency-allowlist.txt",
    ".git/hooks",
)
# The policy guards themselves: an agent must not rewrite the very guard the compiled hook executes.
GUARD_SOURCES = re.compile(r"\.agents/policies/.*implementations")
REASON = "shell write touching agent config is not allowed -- an agent must not edit its own guardrails. Regenerate managed files with `chock sync`, or have a human approve by including 'chock: approved-config-change' in the command."


def hit(path: str) -> bool:
    """Whether a path names something this guard protects (backslashes read as slashes)."""
    normal = path.replace("\\", "/")
    return any(part in normal for part in PROTECTED) or GUARD_SOURCES.search(normal) is not None


def check(raw: str) -> str | None:
    """The reason a command edits protected files, or None; a human's marker in the command line passes."""
    if MARKER in raw:
        return None
    if any(writes_files(cmd, hit) for cmd in commands(raw)):
        return REASON
    return None


def run(argv: list[str]) -> int:
    """Exit 1 blocks, 2 reports a guard fault (never a verdict), 0 allows."""
    try:
        reason = check(os.environ.get("CHOCK_RAW_COMMAND") or shlex.join(argv))
    except Exception as exc:  # noqa: BLE001 -- a guard fault must not look like a block
        print(f"protect-agent-config: internal error ({type(exc).__name__}); command not checked", file=sys.stderr)
        return 2
    if reason:
        print(f"BLOCKED: {reason}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:]))
