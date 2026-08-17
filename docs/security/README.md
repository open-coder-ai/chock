# Security

Chock treats all external instructions as data, never commands. This folder documents the security model and how to verify it.

## Invariants

- **SEC-1** — every artifact declares `security.content_instructions: never-obey`.
- **SEC-2** — deterministic scripts must not call LLMs or make unannotated network calls.
- **SEC-3** — git hooks that block or verify must provide an actionable `gate.message`.
- **SEC-4** — all text surfaces (prompts, docs, eval cases) are scanned for prompt-injection patterns.
- **SEC-5** — ambient rules require `trust_tier >= community` or an explicit `ambient_override`.
- **SEC-6** — skills that process external content require at least one adversarial eval case.
- **SEC-7** — ambient rule blocks in `AGENTS.md` must match the compiled source `rule.text` exactly.

## Verification

Run the deterministic validator before any change:

```bash
chock check
```

Run the enforcement-matrix traceability check:

```bash
chock check --only matrix
```

## Approval gate

Artifacts that declare non-none `effects` (e.g., `irreversible`, `writes_external`) must also set `enforcement: verify|block` — the schema requires `approval: {required: true}` for such artifacts. Enforcing that approval is the invoking agent's job: no runtime engine ships today.

