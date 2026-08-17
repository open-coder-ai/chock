# Template: hook.gate (hooks)

Declarative block-level gates live under `hook.gate` in `manifest.yaml`. `chock compile` emits the shim.
Replace `TODO` fields with real values.

```yaml
hook:
  gate:
    kind: content_regex
    "on": [commit]
    action: block
    message: >
      POLICY_RULE. Instead: COMPLIANT_ALTERNATIVE.
    params:
      content_pattern: 'TODO'
```

Rules for generated gates:

- deterministic: no LLM calls, no network in the gate itself
- `message` always names a compliant alternative
- escape hatches (if any) are declared in `params` and documented in the policy changelog
- the compiler wires each target surface; maintain `hook.gate` in `manifest.yaml` only
