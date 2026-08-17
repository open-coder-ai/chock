# Grok Build CLI adapter

The Grok Build CLI adapter is a thin pointer to the agent-agnostic Chock core.

Verified against: https://docs.x.ai/build/overview and https://x.ai/news/grok-build-cli (Grok Build reads `AGENTS.md`, `CLAUDE.md`, and the `.claude/` ecosystem natively).

## Files

- `.grok/GROK.md` — optional agent-readable wrapper that points to `AGENTS.md`

Grok Build reads `AGENTS.md` natively, so this file is only a convenience marker.

## Pointers

- Core rules: `AGENTS.md`
- Skills: `.agents/skills/`
- Policies: `.agents/policies/`
- Validator: `the `chock check` CLI (src/chock/validation/)`
