# Rules

Rules are ambient guidance that applies to all work in a repo.

## Where rules live

Rules live in `.agents/policies/<rule-id>/` and are compiled into `AGENTS.md`.

## Rule folder contents

- `manifest.yaml` — manifest with `artifact: rule`
- `evals/suite.yaml` — eval cases

## How to create a rule

Use the `policy-init` skill from the Chock framework repo.
