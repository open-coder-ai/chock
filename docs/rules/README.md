# Rules

Rules are ambient guidance that applies to all work in a repo.

## Where rules live

- `AGENTS.md` — compiled always-on rules
- `.agents/policies/<rule-id>/` — source rule folder

## Rule folder contents

- `manifest.yaml` — manifest with `artifact: rule`
- `evals/suite.yaml` — eval cases

## How to write a rule

1. Keep the rule text to two lines or less.
2. Put examples and rationale in `docs/rules/<rule-id>.md` if needed.
3. Validate with the Chock validator.

## Compiling into AGENTS.md

The framework compiles selected rules into the `AGENTS.md` file. Do not hand-edit the compiled block in `AGENTS.md`; edit the source rule folder and regenerate.
