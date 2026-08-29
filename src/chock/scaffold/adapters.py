"""Per-agent instruction files: agentseam decides paths and shared-file coverage.

Split out of `init.py` when that file outgrew the 300-line review budget. Deciding what an
adapter is and writing it is a different activity from scaffolding a repo.

Whole-file branded templates (`.cursor/rules/chock.mdc`, `.windsurf/rules/chock.md`, ...)
are gone: `agentseam.instructions` (marker-block / shared-file model, owner decision #8)
now decides both the path an agent's instructions live at and whether it reads AGENTS.md
natively -- most of chock's supported agents do, per agentseam's `reads_shared()`, so most
of them get no dedicated file at all any more, only a block in the one AGENTS.md every
agent already needs. The agents that do not read AGENTS.md natively still get a small
marker-delimited pointer in their own file, coexisting with whatever else is there --
never a whole-file claim the way the old templates made one.
"""

from __future__ import annotations

from pathlib import Path

from agentseam import instructions as agentseam_instructions

from chock.compile.surfaces import parse_agent_selection as _parse_agent_selection
from chock.scaffold.templates import _preserve_or_write, packaged_template

#: Aider is the one agent agentseam's `instructions` module cannot fully cover: it "reads
#: nothing by convention... the files listed under `read:` in .aider.conf.yml and nothing
#: else" (agentseam's own `instructions.py` docstring, which names this exact gap). A
#: marker block in CONVENTIONS.md is real but inert without this real config file telling
#: Aider to load it -- so chock still ships it directly, the supplement agentseam's own
#: comment anticipates a "sibling guardrail" providing.
_AIDER_CONF_REL = ".aider.conf.yml"

#: chock's own agent id -> the agentseam agent whose `instructions` row governs it. Every
#: id chock has ever scaffolded a wrapper for has a row; `copilot` and `vscode` collapse to
#: the same one (`vscode_copilot`) per agentseam's own recorded finding that `copilot` has
#: no live dispatch adapter of its own -- see `compile/surfaces.py`'s `_MATRIX_AGENT` for
#: the same collapse on the enforcement side.
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

#: The pointer every agent's own file (when it needs one at all) carries. Content, not
#: mechanism -- agentseam decides where this text lands and whether it lands at all for a
#: given agent; chock owns only what it says.
POINTER_TEXT = (
    "# Chock\n\n"
    "Authoritative rules and conventions: `AGENTS.md` (repo root) — read it before any work.\n"
    "Boundaries: never read `README.md`; read `docs/` only when asked."
)


def parse_agent_selection(groups: list[str]) -> list[str]:
    """Split comma- or space-separated --agents values; reject names not in CHOCK_AGENT.

    Thin wrapper over the shared parser in `chock.compile.surfaces` -- the incident that
    motivated it (a path swallowed into the agent list, silently filtered to an empty
    selection that deselected every wrapper) is documented there. This wrapper exists so
    scaffold-side callers validate against CHOCK_AGENT, the set of agents init can write.
    """
    return _parse_agent_selection(groups, valid=CHOCK_AGENT)


def write_instructions(repo_root: Path, selected: list[str]) -> dict[str, str]:
    """Write chock's pointer as a marker block for every selected agent, via agentseam's
    shared-file model. Returns {path: "created"|"updated"|"unchanged"}.

    No `force` parameter: unlike the old whole-file templates, a marker block never
    overwrites adopter content -- it only ever replaces its own delimited region, so there
    is nothing here that force-overwrite protection needs to guard.
    """
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
    """Strip chock's marker block for agents no longer selected. Returns {path: "cleaned"}.

    A file left holding nothing but whitespace once its block is stripped is an orphan the
    old block was the only reason to have, not adopter content -- delete it so
    init/sync/remove round-trips to no file at all, the same way it started. The shared
    AGENTS.md is never deleted this way: it exists independently of any agent selection.
    """
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
                pass  # directory still has other files; only remove it when empty
    if "aider" in deselected:
        conf = Path(repo_root) / _AIDER_CONF_REL
        if conf.exists() and conf.read_text(encoding="utf-8") == packaged_template(_AIDER_CONF_REL):
            conf.unlink()
            removed[_AIDER_CONF_REL] = "cleaned"
    return removed
