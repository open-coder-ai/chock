"""Per-agent instruction files: agentseam decides paths and shared-file coverage."""

from __future__ import annotations

from pathlib import Path

from agentseam import instructions as agentseam_instructions

from chock.compile.surfaces import parse_agent_selection as _parse_agent_selection
from chock.scaffold.templates import _preserve_or_write, packaged_template

_AIDER_CONF_REL = ".aider.conf.yml"

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

POINTER_TEXT = (
    "# Chock\n\n"
    "Authoritative rules and conventions: `AGENTS.md` (repo root) — read it before any work.\n"
    "Boundaries: read `README.md` and `docs/` only when the task is to change them."
)


def deselected_agents(selected: list[str]) -> list[str]:
    """Chock agent ids to pass to `remove_instructions` for a given `selected` set."""
    selected_targets = {CHOCK_AGENT[a] for a in selected if a in CHOCK_AGENT}
    return sorted(a for a in CHOCK_AGENT if a not in selected and CHOCK_AGENT[a] not in selected_targets)


def parse_agent_selection(groups: list[str]) -> list[str]:
    """Split comma- or space-separated --agents values; reject names not in CHOCK_AGENT."""
    return _parse_agent_selection(groups, valid=CHOCK_AGENT)


def write_instructions(repo_root: Path, selected: list[str]) -> dict[str, str]:
    """Write chock's pointer as a marker block for every selected agent, via agentseam's"""
    targets = sorted({CHOCK_AGENT[a] for a in selected if a in CHOCK_AGENT})
    if not targets:
        return {}
    written = agentseam_instructions.write(POINTER_TEXT, targets=targets, repo_root=str(repo_root))
    if "aider" in selected:
        conf = Path(repo_root) / _AIDER_CONF_REL
        if not _preserve_or_write(conf, packaged_template(_AIDER_CONF_REL), force=False):
            written[_AIDER_CONF_REL] = "written"
    return written


def remove_instructions(repo_root: Path, deselected: list[str]) -> dict[str, str]:
    """Strip chock's marker block for agents no longer selected. Returns {path: "cleaned"}."""
    targets = sorted({CHOCK_AGENT[a] for a in deselected if a in CHOCK_AGENT})
    if not targets:
        return {}
    removed = agentseam_instructions.remove(targets=targets, repo_root=str(repo_root))
    for rel in removed:
        if rel == agentseam_instructions.SHARED_FILE:
            continue
        path = Path(repo_root) / rel
        if path.exists() and not path.read_text(encoding="utf-8").strip():
            path.unlink()
            parent = path.parent
            try:
                parent.rmdir()
            except OSError:
                pass
    if "aider" in deselected:
        conf = Path(repo_root) / _AIDER_CONF_REL
        if conf.exists() and conf.read_text(encoding="utf-8") == packaged_template(_AIDER_CONF_REL):
            conf.unlink()
            removed[_AIDER_CONF_REL] = "cleaned"
    return removed
