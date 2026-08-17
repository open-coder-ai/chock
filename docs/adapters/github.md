# GitHub Copilot adapter

The GitHub Copilot adapter is a thin pointer to the agent-agnostic Chock core.

## Files

- `.github/copilot-instructions.md` — agent-readable wrapper that points to `AGENTS.md`
- `docs/README.md` — human documentation

## Pointers

- Core rules: `AGENTS.md`
- Skills: `.agents/skills/`
- Wiring: `src/chock/scaffold/adapters.py`
- Validator: `the `chock check` CLI (src/chock/validation/)`
