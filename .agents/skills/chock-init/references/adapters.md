:= chock-context

# Agent adapters

Chock keeps `AGENTS.md` as the single source of truth and auto-generates thin wrappers for agents that do not read `AGENTS.md` natively.

## Classification

| Category | Agents | Auto-discovers `AGENTS.md`? | Files generated |
|---|---|---|---|
| Standard adopters | codex, cursor, windsurf, devin, grok, kimi-code, antigravity (also qwen, jules, goose, amp, cody — native `AGENTS.md` readers with no wrapper and no `--agents` name) | Yes | `AGENTS.md` only; optional wrappers for cursor/windsurf/antigravity and optional pointers for devin, grok, kimi-code |
| Proprietary holdouts | claude, copilot, gemini, replit | No | `.claude/CLAUDE.md`, `.github/copilot-instructions.md`, `.gemini/GEMINI.md`, `replit.md` |
| Config-dependent | aider, vscode, tabnine | Conditional | `CONVENTIONS.md` + `.aider.conf.yml`, `.github/agents/*.agent.md`, `guidelines.md` |

## File-specific notes

- **Claude Code**: reads `CLAUDE.md` at repo root or `.claude/CLAUDE.md` at session start; also supports `.claude/rules/*.md` for scoped rules.
- **Cursor**: modern rules live in `.cursor/rules/*.mdc` with YAML frontmatter (`alwaysApply: true` for always-on). Legacy `.cursorrules` root file is still supported.
- **Windsurf**: modern rules live in `.windsurf/rules/*.md` with YAML frontmatter (`trigger: always_on`). Legacy `.windsurfrules` root file is still supported.
- **GitHub Copilot**: project-wide instructions from `.github/copilot-instructions.md`; path-specific instructions via `.github/instructions/*.instructions.md`.
- **Gemini CLI**: `GEMINI.md` files are loaded hierarchically (global, project root, `.gemini/`, subdirectories).
- **Antigravity CLI**: reads rules hierarchically from `.agents/rules/*.md`, `GEMINI.md`, and `AGENTS.md`. Optional `.agents/rules/chock.md` rule.
- **Aider**: `CONVENTIONS.md` is a read-only context file; load with `/read CONVENTIONS.md`, `aider --read CONVENTIONS.md`, or auto-load via `.aider.conf.yml` (`read: CONVENTIONS.md`).
- **VS Code**: custom agents are `.agent.md` files in `.github/agents/` (workspace scope) or `.claude/agents/` (Claude format), with YAML frontmatter.
- **Grok Build**: reads `AGENTS.md` natively; also compatible with `CLAUDE.md` and `.claude/` content. Optional `.grok/GROK.md` pointer.
- **Kimi Code**: reads `AGENTS.md` natively, including `.kimi-code/AGENTS.md` and `.kimi/AGENTS.md` hierarchically.
- **Qwen Code / Jules / Goose / Amp / Sourcegraph Cody**: read `AGENTS.md` natively; thin wrappers are optional pointers.
- **Replit Agent**: uses `replit.md` for project-level context.
- **Tabnine**: uses `guidelines.md` for project-level agent guidelines, or `.tabnine/guidelines.md`.

## Selection

Agent names that generate files are the exact `--agents` vocabulary (`chock init --agents
copilot,kimi-code`) — the names in `AGENT_FILES`. Native `AGENTS.md` readers with no
wrapper (qwen, jules, goose, amp, cody) have no flag name. An unknown name aborts the run,
so a marketing spelling that is not on the flag's valid list is a wrong name here too.

- `agent_agnostic == true` → generate all supported adapters.
- Explicit agent list → generate only the adapters requested by the user.
- No selection → claude, copilot, gemini: the holdouts that need their own file and do not create one themselves. Replit is also a holdout, but Replit Agent auto-creates `replit.md` inside its workspace — opt in with `--agents replit`.
- Removing an adapter on re-run deletes its derived file and any empty parent folder.
