# Skills

A skill is a reusable instruction set stored in a single folder.

## Where skills live

- Framework meta-skills: `.agents/skills/<name>/`
- Business skills in a user repo: `.agents/skills/<name>/`

## Skill folder contents

- `SKILL.md` — activation surface and minimal contract; its frontmatter **is** the manifest
- `interface.yaml` — optional sibling for `input_schema`, `output_schema`, and `evaluation`
- `references/` — depth loaded on demand
- `examples/` — mined real-code examples
- `evals/suite.yaml` — eval cases

A skill folder must not contain both `SKILL.md` and `manifest.yaml` — that is a hard error.

## How to create a skill

Use the `policy-init` skill from the Chock framework repo. It interviews you, drafts evals first, and generates a self-contained folder.

## Conventions

- Keep `SKILL.md` under 150 lines.
- Keep `description` under 500 characters.
- Put depth in `references/`, never inline it in the body.
- Every rule in `## Rules` should be one or two lines.
- Scripts must be deterministic: no LLM calls, no network, no plaintext secrets.
