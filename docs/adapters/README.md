:= chock-context

# Adapters

Adapters map the agent-agnostic Chock core to agent-specific surfaces.

## Agent-specific entry points

Each supported agent has a native file that delegates back to `AGENTS.md`:

- Claude Code: `.claude/CLAUDE.md`
- Cursor: `.cursor/rules/*.mdc` (modern), `.cursorrules` (legacy fallback)
- Devin: `.devin/README.md`
- Windsurf: `.windsurf/rules/*.md` (modern), `.windsurfrules` (legacy fallback)
- Codex: `codex.md`
- GitHub Copilot: `.github/copilot-instructions.md`
- Gemini CLI: `.gemini/GEMINI.md`
- Grok Build: `.grok/GROK.md`
- Kimi Code: `.kimi-code/AGENTS.md`
- Aider: `CONVENTIONS.md` + `.aider.conf.yml`
- VS Code: `.github/agents/*.agent.md`
- Replit Agent: `replit.md`
- Tabnine: `guidelines.md`
- Antigravity CLI: `.agents/rules/*.md`

These files are thin wrappers. The actual rules and skills live in `AGENTS.md`, `.agents/skills/`, and `.agents/policies/`.

## Contents

- [Claude](./claude.md)
- [Cursor](./cursor.md)
- [Devin](./devin.md)
- [Windsurf](./windsurf.md)
- [Codex](./codex.md)
- [GitHub Copilot](./github.md)
- [Gemini CLI](./gemini.md)
- [Grok Build](./grok.md)
- [Kimi Code](./kimi.md)
- [Aider](./aider.md)
- [VS Code](./vscode.md)
- [Replit Agent](./replit.md)
- [Tabnine](./tabnine.md)
- [Antigravity CLI](./antigravity.md)
- [The skills bridge — why only Claude Code](./skills-bridge.md)
