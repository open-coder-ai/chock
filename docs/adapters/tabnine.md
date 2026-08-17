# Tabnine adapter

The Tabnine adapter loads Chock conventions as project-level agent guidelines.

Verified against: https://docs.tabnine.com/main/getting-started/tabnine-agent/guidelines (Tabnine Agent guidelines).

## Files

- `guidelines.md` — project-level agent guidelines that point to `AGENTS.md`

Tabnine Agent reads `guidelines.md` for project-specific instructions.

## Pointers

- Core rules: `AGENTS.md`
- Skills: `.agents/skills/`
- Policies: `.agents/policies/`
- Validator: `the `chock check` CLI (src/chock/validation/)`
