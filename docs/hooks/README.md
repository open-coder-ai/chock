# Hooks

Hooks are block or verify gates enforced at commit time through git hooks.

## Where hooks live

- `.agents/policies/<hook-id>/` — source hook folder
- `.git/hooks/` — runtime git hook after installation

## Hook folder contents

- `manifest.yaml` — manifest with `artifact: hook` and `enforcement: block|verify`
  and a `hook.gate` block describing the trigger, message, and params
- `evals/suite.yaml` — eval cases

## How to write a hook

1. Pick a `kind` and fill `params` under `hook.gate` in `manifest.yaml` (see [Gate DSL](../../spec/gate-dsl.md)).
2. `chock compile` emits the shim + vendored runner — no script to write.
3. The failure message must name the compliant alternative.

## Scripts

Scripts must not call an LLM, use the network, or require plaintext secrets.
