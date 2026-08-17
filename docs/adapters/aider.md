# Aider adapter

The Aider adapter loads Chock conventions as a read-only context file.

Verified against: https://aider.chat/docs/usage/conventions.html (Aider conventions files).

## Files

- `CONVENTIONS.md` — read-only conventions file
- `.aider.conf.yml` — config that auto-loads `CONVENTIONS.md`

Aider does not auto-discover project instruction files; load them with `/read CONVENTIONS.md`, `aider --read CONVENTIONS.md`, or via `.aider.conf.yml`.

## Pointers

- Core rules: `AGENTS.md`
- Skills: `.agents/skills/`
- Policies: `.agents/policies/`
- Validator: `the `chock check` CLI (src/chock/validation/)`
