# Chock Enforcement Matrix

Every spec invariant must appear in this matrix with the check(s) that enforce it. This file is the source of truth for traceability; CI verifies that every invariant ID in `spec/` is listed here and that every row in this matrix has a corresponding check in the validator or CI pipeline.

## How to read this matrix

| Column | Meaning |
|---|---|
| ID | Invariant identifier (`SEC-*`, `DET-*`, `EFF-*`, `INT-*`, `HRM-*`) |
| Spec | Spec section that defines the invariant |
| Check | Concrete tool or code path that enforces it |
| Severity | `error` / `warning` / `info` |
| Notes | Exceptions, manual gates, or planned future work |

## Security invariants (SEC)

| ID | Spec | Check | Severity | Notes |
|---|---|---|---|---|
| SEC-1 | `spec/policy-spec.md` §10 | `the validator`: `security.content_instructions == "never-obey"` for all artifact types | error | Applies to skill, hook, rule, workflow, subagent |
| SEC-2 | `spec/policy-spec.md` §10 | `the validator`: static scan of `scripts/` under code/hybrid skills and hook implementations for LLM/network calls | error | Network calls warn unless `network` effect is declared with `verify`/`block` enforcement and approval wiring (EFF-1) |
| SEC-3 | `spec/policy-spec.md` §10 | `the validator`: `gate.message` required for hooks with `action: block` or `verify` | error | Message must be actionable (verified by eval suite, not regex) |
| SEC-4 | `spec/policy-spec.md` §10 | `the validator`: `scan_text_surfaces()` covers all `.md`/`.yaml`/`.txt` files under artifact folders plus manifest text fields and eval prompts | error | Adversarial eval cases downgraded to `info` when category is `adversarial`/`security` |
| SEC-5 | `spec/policy-spec.md` §10 | `the validator`: `check_ambient_tier()` requires `trust_tier >= community` or `ambient_override: true` for rules wired into ambient files | error | Manual migration required for existing `sandbox` ambient rules |
| SEC-6 | `spec/policy-spec.md` §10 | `the validator`: `security.processes_external_content: true` requires ≥1 adversarial eval case | error | `policy-init` skill and template set the flag when content is mined |
| SEC-7 | `spec/policy-spec.md` §10 | `the validator`: `check_ambient_rule_blocks()` compares `AGENTS.md` marked blocks against source policy `rule.text` | error | Canonical form: exact `rule.text` pasted between markers |

## Deterministic-first invariants (DET) — Phase 2

| ID | Spec | Check | Severity | Notes |
|---|---|---|---|---|
| DET-1 | `spec/policy-spec.md` §11 | `the validator`: `check_scripts_shipped()` — `skill.skill_type: code|hybrid` requires non-empty `scripts/` with an executable script | error | `scripts.entrypoint` optional for skills but must resolve if present; standalone script artifacts are not allowed |
| DET-2 | `spec/policy-spec.md` §11 | `the registry`: sha256 hashes per script; `the validator`: `check_script_integrity()` verifies for production/verified+ artifacts | error | Stale registry triggers a rescan, not a silent pass |
| DET-3 | `spec/optimization.md` §2 | `optimize` skill: `determinize_edit` edit type; `the validator`: `check_determinization_heuristic()` flags NL skills with regex/command sequences | info | Human review required for `determinize_edit` |
| DET-4 | `spec/policy-spec.md` §12 + `spec/methodology.md` | `src/chock/packs/_skills/policy-init/references/taxonomy.md` requires a pre-walk `determinism_scan` that splits deterministic_parts from judgment_parts; mechanical parts route to a code/hybrid skill with a committed script. `policy-init` eval cases verify the split and routing. | eval | Enforced by eval suite; post-hoc backstop is DET-3 |

## Effects and approvals (EFF) — Phase 3

| ID | Spec | Check | Severity | Notes |
|---|---|---|---|---|
| EFF-1 | `spec/policy-spec.md` §12 + `spec/methodology.md` D1 | Schemas require explicit `effects` for `skill`/`subagent`; `the validator`: `check_effects_and_approval()` requires `enforcement: verify\|block` and `approval: {required: true}` when any effect is `writes_external` or `irreversible` | error | `writes_workspace` triggers git-state capture; `read_only`/`reads_private`/`network` are informational |

## Agent-driven orchestration (ORC)

| ID | Spec | Check | Severity | Notes |
|---|---|---|---|---|
| ORC-1 | `spec/policy-spec.md` §13 | `check_composition_contract()`: workflow phases, invocation targets, bounded fan-out, and correlation keys | error | Host agent performs dispatch; validator checks the contract |
| ORC-2 | `spec/policy-spec.md` §13 | `check_composition_contract()`: phase and workflow monitoring are required | error | Missing results route to `needs_handoff` |
| ORC-3 | `spec/policy-spec.md` §13 | `check_composition_contract()` and subagent interface checks require work-item handoff fields | error | Required fields: work_item_id, phase, status, outcome, error |
| ORC-4 | `spec/policy-spec.md` §13 | `check_composition_contract()`: fan-out isolation and human checkpoint approval bindings | error | Write-capable integrations must enforce this at the adapter boundary |
| ORC-5 | `spec/policy-spec.md` §13 | `check_composition_contract()`: workflow name prefix | warning | Default prefix is `Orchestrator /` |

## Interface rigor (INT) — Phase 5

| ID | Spec | Check | Severity | Notes |
|---|---|---|---|---|
| INT-1 | `spec/policy-spec.md` §13 | `manifest.schema.json` (via the `skill` artifact conditional and `manifest.skill.json`) requires `input_schema.additionalProperties: false`, property-level `type` and `description`; `the validator` reports schema violations | error | Applies to `code` and `hybrid` skill artifacts; `nl` skills are exempt from I/O schemas. `interface.yaml` supplies these schemas when present. |
| INT-2 | `spec/policy-spec.md` §13 | `manifest.schema.json` (via the `skill` artifact conditional) requires `output_schema.properties.outcome` enum `[success, failure, needs_handoff]` and `additionalProperties: false` | error | Applies to `code` and `hybrid` skill artifacts; `nl` skills are exempt. Gives optimizer clean conformance signal. `interface.yaml` supplies these schemas when present. |
| INT-3 | `spec/policy-spec.md` §13 | `the validator`: `check_verb_first_naming()` warns when a draft/sandbox executing artifact ID does not start with a verb | warning | Existing IDs are grandfathered |

## Hermetic execution (HRM) — Phase 5

| ID | Spec | Check | Severity | Notes |
|---|---|---|---|---|
| HRM-1 | `spec/policy-spec.md` §14 | Eval-level behavior case per meta-skill (`policy-init`, `validate`, `eval`, `optimize`, `chock-init`) proves configuration is read from the artifact's own folder or `.chock/config.yaml`, not conversation instructions | eval | Not statically checkable; enforced by eval suite |

## Policy toggles (POL)

| ID | Spec | Check | Severity | Notes |
|---|---|---|---|---|
| POL-1 | `spec/policy-spec.md` §17 | `the validator`: `check_policy_toggles()` errors if `policies.disabled` contains a policy with `mandatory: true` | error | CLI `disable` also blocks this with exit code 2 |
| POL-2 | `spec/policy-spec.md` §17 | `the validator`: `check_policy_toggles()` warns on unknown ids in `policies.disabled` or `policies.overrides` | warning | Validates config without crashing on typos |
| POL-3 | `spec/policy-spec.md` §17 | `the validator`: `check_policy_toggles()` warns when `scan-secrets` or `protect-main-branch` is downgraded to advisory | warning | Catch accidental weakening of block guards |

## Operational checks (WRP/TPL/FRS) — Phase 5

| ID | Spec | Check | Severity | Notes |
|---|---|---|---|---|
| WRP-1 | `spec/policy-spec.md` §15 | `the validator`: `check_adapter_integrity()` verifies every generated adapter file references `AGENTS.md` | warning | Applies to the 16 adapter files listed in `AGENTS.md` |
| TPL-1 | `spec/policy-spec.md` §15 | Mirrors: `src/chock/packs/_skills/policy-init/assets/templates/**` (recursive) with `.agents/skills/policy-init/assets/templates/**`; keep in sync manually | warning | Copy the packaged source to the compiled folder when it changes |
| FRS-1 | `spec/policy-spec.md` §15 | `the validator`: `check_adapter_integrity()` requires a `fetched_at` or `updated_at` freshness marker and warns if it is older than 30 days | warning | Marker format: `YYYY-MM-DD` in a comment or frontmatter |
| SCH-1 | `spec/policy-spec.md` §15 | `chock install-skills` copies canonical `manifest*.json` schemas from `src/chock/validation/schemas/` into `.agents/skills/validate/assets/`; the validator uses the installed package's own schemas | error | Re-install skills to refresh schemas |
| REL-1 | `spec/policy-spec.md` §15 | `the validator`: `check_release_consistency()` compares `VERSION`, `pyproject.toml`, and the top `CHANGELOG.md` entry | error | Bump all three together in every release |
| AMB-1 | `spec/policy-spec.md` §15 | `the validator`: `check_ambient_token_budget()` estimates tokens across `chock:rules` blocks in `AGENTS.md` | warning | Soft budget from §4 (`ambient_total_tokens_soft`) |

## CI traceability checks

- `chock check --only matrix` verifies that every invariant ID in `spec/` appears in this matrix.
- `chock check --only matrix` verifies that every row in this matrix has a non-empty `Check` column.
- CI runs this script before the validator.
