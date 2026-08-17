# Skills

A skill is a reusable instruction set stored in a single folder.

## Where skills live

Business skills live in `.agents/skills/<name>/`.

## Skill folder contents

- `SKILL.md` — activation surface and minimal contract
- `manifest.yaml` — manifest with schema, evaluation, and lifecycle
- `references/` — depth loaded on demand
- `examples/` — mined real-code examples
- `evals/suite.yaml` — eval cases

## How to create a skill

Use the `policy-init` skill from the Chock framework repo.
