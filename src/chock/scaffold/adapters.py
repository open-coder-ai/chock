"""Per-agent adapter files: which ones each agent needs, and writing them.

Split out of `init.py` when that file outgrew the 300-line review budget. Deciding what an
adapter is and writing it is a different activity from scaffolding a repo.
"""

from __future__ import annotations

from pathlib import Path

from chock.compile.surfaces import parse_agent_selection as _parse_agent_selection
from chock.scaffold.templates import _preserve_or_write, packaged_template

AGENT_FILES: dict[str, list[str]] = {
    "claude": [".claude/CLAUDE.md"],
    "cursor": [".cursor/rules/chock.mdc", ".cursorrules"],
    "windsurf": [".windsurf/rules/chock.md", ".windsurfrules"],
    "devin": [".devin/README.md"],
    "codex": ["codex.md"],
    "grok": [".grok/GROK.md"],
    "kimi-code": [".kimi-code/AGENTS.md"],
    "copilot": [".github/copilot-instructions.md"],
    "gemini": [".gemini/GEMINI.md"],
    "vscode": [".github/agents/chock.agent.md"],
    "aider": ["CONVENTIONS.md", ".aider.conf.yml"],
    "replit": ["replit.md"],
    "tabnine": ["guidelines.md"],
}


def parse_agent_selection(groups: list[str]) -> list[str]:
    """Split comma- or space-separated --agents values; reject names not in AGENT_FILES.

    Thin wrapper over the shared parser in `chock.compile.surfaces` -- the incident that
    motivated it (a path swallowed into the agent list, silently filtered to an empty
    selection that deselected every wrapper) is documented there. This wrapper exists so
    scaffold-side callers validate against AGENT_FILES, the set of agents init can write.
    """
    return _parse_agent_selection(groups, valid=AGENT_FILES)


def _write_wrapper(repo_root: Path, agent: str, force: bool) -> list[str]:
    """Write an agent's adapter files from the packaged templates. Returns those left alone.

    The per-adapter frontmatter and body used to be assembled from inline constants here.
    The packaged files already carry both, and `references/templates.md` documents a 1:1
    template-to-output mapping -- so assembling the content instead of reading it made the
    code contradict its own published contract, and let the two drift apart unnoticed.
    """
    return [r for r in AGENT_FILES.get(agent, []) if _preserve_or_write(repo_root / r, packaged_template(r), force)]


def _remove_deselected_wrappers(repo_root: Path, selected: set[str], force: bool) -> list[str]:
    """Delete wrappers for agents that are no longer selected. Returns those left alone.

    Deleting an edited wrapper destroys adopter content as thoroughly as overwriting one,
    and `--agents` defaults to three agents -- so a bare re-run after `init --agents cursor`
    used to delete a hand-tuned `.cursorrules` without a word.
    """
    preserved: list[str] = []
    for agent, files in AGENT_FILES.items():
        if agent in selected:
            continue
        for rel_path in files:
            path = repo_root / rel_path
            if path.exists():
                if not force and path.read_text(encoding="utf-8") != packaged_template(rel_path):
                    preserved.append(rel_path)
                    continue
                path.unlink()
                parent = path.parent
                try:
                    parent.rmdir()
                except OSError:
                    pass  # directory still has other files; only remove it when empty
    return preserved


#: Where the policies that used to be bundled now live.
