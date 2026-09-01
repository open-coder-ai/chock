"""The one chock-agent-id -> agentseam-vendor-id alias table every module reads."""

from __future__ import annotations

CHOCK_AGENT: dict[str, str] = {
    "claude": "claude_code",
    "cursor": "cursor",
    "windsurf": "windsurf",
    "devin": "devin",
    "codex": "codex_cli",
    "grok": "grok",
    "kimi-code": "kimi_code",
    "copilot": "vscode_copilot",
    "gemini": "gemini_cli",
    "vscode": "vscode_copilot",
    "aider": "aider",
    "replit": "replit",
    "tabnine": "tabnine",
    "antigravity": "antigravity",
}
