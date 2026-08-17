# Hooks

Hooks are deterministic, read-only guards enforced at commit/push time through git hooks. They are **not** agent-runtime command interception; for command-time guidance, use `## Rules` in `AGENTS.md`.

## Where hooks live

Hooks live in `.agents/policies/<hook-id>/`.

## Hook folder contents

- `manifest.yaml` — manifest with `artifact: hook`, `enforcement: block|verify`, and a `hook.gate` block describing the trigger and message
- `evals/suite.yaml` — eval cases

## Installation

Run `chock sync` to register the compiled git hooks under `.git/hooks/`. Re-run after adding or removing hooks.

## Default hooks

None — init installs no hooks. Install from the catalog (`chock add <id>`), then run `chock sync --repo .`.

## How to create a hook

Use the `policy-init` skill from the Chock framework repo.
