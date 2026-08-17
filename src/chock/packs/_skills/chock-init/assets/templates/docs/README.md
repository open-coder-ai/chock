# Chock setup

This repo uses Chock for agent policy engineering. This folder contains human-readable documentation only. Agents must not read files here.

## Structure

- `.agents/skills/` — your business skills
- `.agents/policies/` — your rules, hooks, and policies
- `docs/` — human documentation
- `AGENTS.md` — agent-readable rules

## Next steps

1. Create your first policy using the `/policy-init` skill installed in your agent's skill directory.
2. Validate with `chock check`.
