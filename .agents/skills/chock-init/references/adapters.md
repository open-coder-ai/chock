:= chock-context

# Agent instructions

Chock keeps `AGENTS.md` as the single source of truth. `agentseam.instructions` decides
whether a given agent reads `AGENTS.md` natively; init writes a dedicated file only for
the agents that do not. Every dedicated file carries a
marker-delimited block (`<!-- agentseam:begin -->` / `<!-- agentseam:end -->`), never a
whole-file claim -- content outside the markers, and any other file in the repo, is
untouched.

## Classification

Per `agentseam.instructions.reads_shared(agent)`, verified against each vendor's own
discovery behaviour.

| Reads `AGENTS.md` natively (no dedicated file) | Needs its own file (marker block only) |
|---|---|
| cursor, windsurf, codex, copilot, vscode (both collapse to `vscode_copilot`), gemini, kimi-code | claude, aider, devin, grok, replit, tabnine, antigravity |

## File-specific notes

- **Claude Code**: reads `CLAUDE.md` at the repo root (agentseam's preferred path) at session start.
- **Aider**: reads nothing by convention -- only what `.aider.conf.yml`'s `read:` list names. `agentseam.instructions` cannot express that config file, so chock ships it directly (`scaffold/adapters.py`, `_AIDER_CONF_REL`) alongside the marker block it writes into `CONVENTIONS.md`.
- **Devin**: `.devin/README.md`.
- **Grok Build**: `.grok/GROK.md`.
- **Replit Agent**: `replit.md`. Replit Agent also auto-creates its own `replit.md` inside its workspace, so a chock-written one duplicates what the host does — opt in with `--agents replit`.
- **Tabnine**: `guidelines.md`.
- **Antigravity**: `.agents/rules/agentseam.md`.
- Every agent in the left column needs nothing further: their own discovery already reaches `AGENTS.md`, wherever chock's marker block in it currently sits.

## Selection

Agent names that can get a dedicated file are the exact `--agents` vocabulary (`chock init
--agents copilot,kimi-code`) — the names in `CHOCK_AGENT`. Native `AGENTS.md` readers with
no flag name at all (qwen, jules, goose, amp, cody) are not in this map; they need nothing
from chock regardless of selection. An unknown name aborts the run, so a marketing spelling
that is not on the flag's valid list is a wrong name here too.

- `agent_agnostic == true` → every agent in `CHOCK_AGENT` is "selected"; the right-column
  ones each get a file, the left-column ones get nothing beyond the shared AGENTS.md.
- Explicit agent list → only those agents are selected; the same split applies.
- No selection → claude, copilot, gemini: only claude gets a dedicated file.
- Deselecting an agent on re-run strips its marker block. A file left with nothing outside
  that block is an orphan and is deleted, parent directory included if now empty; adopter
  content added outside the block survives untouched.
