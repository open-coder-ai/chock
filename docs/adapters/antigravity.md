# Antigravity CLI adapter

The Antigravity CLI adapter is a thin pointer to the agent-agnostic Chock core.

Verified against: https://antigravity.google/docs/rules-workflows (Antigravity Rules & Workflows).

## Files

- `.agents/rules/chock.md` — workspace rule with `trigger: always_on` that points to `AGENTS.md`

Antigravity CLI discovers rules hierarchically in `.agents/rules/*.md`, `GEMINI.md`, and `AGENTS.md`.

Antigravity's current [best-practices documentation](https://antigravity.google/docs/cli/best-practices/) states that the agent automatically parses a workspace `AGENTS.md` on startup.

## Pointers

- Core rules: `AGENTS.md`
- Skills: `.agents/skills/`
- Policies: `.agents/policies/`
- Validator: the `chock check` CLI (src/chock/validation/)
