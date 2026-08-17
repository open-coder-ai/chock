# Claude adapter

The Claude adapter is a thin pointer to the agent-agnostic Chock core.

## Files

- `.claude/CLAUDE.md` — agent-readable wrapper that points to `AGENTS.md`
- `docs/README.md` — human documentation

## Pointers

- Core rules: `AGENTS.md`
- Skills: `.agents/skills/`
- Wiring: `src/chock/scaffold/adapters.py`
- Validator: `the `chock check` CLI (src/chock/validation/)`
