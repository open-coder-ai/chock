:= chock-context

# The skills bridge — why only Claude Code

Chock keeps one canonical skills directory, `.agents/skills/`, and bridges it into an
agent's own discovery path **only when that agent cannot read `.agents/skills/` natively**.
Every bridge is duplicated state that must be kept in sync and swept, and the sweep is a
data-loss surface in a directory the adopter also puts their own skills in — so the bridge
list is kept as short as the ecosystem allows.

## State of the ecosystem (as of August 2026)

Since the SKILL.md format became an open standard (December 2025), `.agents/skills/` has
become the convergent cross-tool location. Of the agents Chock supports:

| Agent | Own skill directory | Reads `.agents/skills/`? | Bridge |
| :--- | :--- | :--- | :--- |
| Claude Code | `.claude/skills/` | no | **yes — the only one** |
| Gemini CLI | `.gemini/skills/` | yes (alias; takes precedence) | no |
| Codex | `~/.agents/skills/` | yes (it is the home) | no |
| Cursor | `.cursor/skills/` | yes | no |
| Devin | `.devin/skills/` | yes | no |
| Copilot / VS Code | `.github/skills/` | yes | no |
| Windsurf | `.windsurf/skills/` | yes (current versions) | no |
| grok, kimi-code, aider, replit, tabnine | — | n/a: no SKILL.md system | no |

The bridge map is `AGENT_BRIDGES` in `src/chock/scaffold/skills_bridge.py` — one line per
agent. Extend it only when an agent ships a skill system that cannot see
`.agents/skills/`; the trend runs the other way.

## Ownership rules

`.claude/skills/` is shared with the adopter's own Claude-native skills, so the bridge
sweep removes only what Chock created: a symlink resolving into `.agents/skills/`, or a
copy carrying a `.chock-bridge` marker (the fallback on Windows without Developer Mode).
Anything else there is the adopter's and is never touched.

## Planned removal

The bridge exists solely because Claude Code does not yet discover `.agents/skills/`. The
day it does, the bridge — and its entire sync-and-sweep surface — should be deleted, not
maintained. Tracked in the repo issues as the skills-bridge removal watch item.
