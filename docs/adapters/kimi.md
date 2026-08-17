# Kimi Code CLI adapter

The Kimi Code CLI adapter is a thin pointer to the agent-agnostic Chock core.

Verified against: https://www.kimi.com/code/docs/en/kimi-code-cli/customization/agents.html (Kimi Code CLI instruction files).

## Files

- `.kimi-code/AGENTS.md` — optional agent-readable wrapper that points to `AGENTS.md`

Kimi Code CLI reads `AGENTS.md` natively from the project root or `.kimi-code/AGENTS.md`, hierarchically.

## Pointers

- Core rules: `AGENTS.md`
- Skills: `.agents/skills/`
- Policies: `.agents/policies/`
- Validator: `the `chock check` CLI (src/chock/validation/)`
