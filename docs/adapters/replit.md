# Replit Agent adapter

The Replit Agent adapter is a thin pointer to the agent-agnostic Chock core.

Verified against: https://docs.replit.com/replitai/replit-dot-md (Replit Agent `replit.md` context file).

## Files

- `replit.md` — agent-readable wrapper that points to `AGENTS.md`

Replit Agent uses `replit.md` for project-level context.

## Pointers

- Core rules: `AGENTS.md`
- Skills: `.agents/skills/`
- Policies: `.agents/policies/`
- Validator: `the `chock check` CLI (src/chock/validation/)`
