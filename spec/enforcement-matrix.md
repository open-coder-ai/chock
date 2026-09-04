# Chock Enforcement Matrix

Every spec invariant must appear in this matrix with the check(s) that enforce it. This file is the source of truth for traceability; CI verifies that every invariant ID in `spec/` is listed here and that every row in this matrix has a corresponding check in the validator or CI pipeline.

## How to read this matrix

| Column | Meaning |
|---|---|
| ID | Invariant identifier (`SEC-*`, `DET-*`, `EFF-*`, `INT-*`, `HRM-*`) |
| Spec | Spec section that defines the invariant |
| Check | Concrete tool or code path that enforces it |
| Severity | `error` / `warning` / `info` / `eval` (enforced by the eval suite, not the validator) / `unautomated` (no code path enforces this row today) |
| Notes | Exceptions, manual gates, or planned future work |
| Dispatch | Which of chock's two check paths runs the mechanism: `engine` (`chock validate`, `src/chock/validation/engine.py`) or `lifecycle` (a `chock check`-only sub-check in `src/chock/lifecycle.py`'s `CHECKS`, not reachable through `chock validate` alone). `n/a` when Severity is `eval`/`unautomated`. Recorded because chock has two dispatch paths and nothing else says which one enforces a row -- reading only one is how an earlier audit produced its own false positives (`discovery/2026-09-04-enforcement-matrix-audit.md` in org-plan). |

`chock check --only mechanisms` (`checks_matrix_mechanisms.py`) verifies every row naming a `` `function()` `` mechanism: the function is defined in `src/`, it is invoked on the `engine` or `lifecycle` dispatch path, and it can emit the severity the row claims.

## Security invariants (SEC)

| ID | Spec | Check | Severity | Notes | Dispatch |
|---|---|---|---|---|---|
| SEC-1 | `spec/policy-spec.md` §10 | `the validator`: `check_security_baseline()` requires `security.content_instructions == "never-obey"` for all artifact types | error | Applies to skill, hook, rule, workflow, subagent | engine |
| SEC-2 | `spec/policy-spec.md` §10 | `the validator`: `check_security_baseline()` — static scan of `scripts/` under code/hybrid skills and hook implementations for LLM/network calls | error | Network calls warn unless `network` effect is declared with `verify`/`block` enforcement and approval wiring (EFF-1) | engine |
| SEC-3 | `spec/policy-spec.md` §10 | `the validator`: `validate_yaml_against_schema()` enforces `manifest.hook.json`'s requirement that `gate.message` (1-1000 chars) be present whenever `hook.gate` is present | error | Message must be actionable (verified by eval suite, not regex). `manifest.hook.json`'s `gate.action` is currently a `const: block` — the schema does not yet accept `verify` as a distinct gate action; this row previously claimed both, which the schema cannot back. Flagged as a Deviation in `plan/chock-g1/reports/w5.md`, not fixed here (not authorized to change what the check does) | engine |
| SEC-4 | `spec/policy-spec.md` §10 | `the validator`: `_scan_text_surfaces()` (called from `check_security_baseline()`) covers all `.md`/`.yaml`/`.txt` files under artifact folders plus manifest text fields and eval prompts | error | Adversarial eval cases downgraded to `info` when category is `adversarial`/`security`. Private in `checks_security.py` — the public name `scan_text_surfaces()` this row previously gave does not exist | engine |
| SEC-5 | `spec/policy-spec.md` §10 | `the validator`: `check_ambient_tier()` requires `trust_tier >= community` or `ambient_override: true` for rules wired into ambient files | error | Manual migration required for existing `sandbox` ambient rules | engine |
| SEC-6 | `spec/policy-spec.md` §10 | `the validator`: `check_eval_first()` requires ≥1 `adversarial`/`security` eval case when `security.processes_external_content: true` | error | `policy-init` skill and template set the flag when content is mined | engine |
| SEC-7 | `spec/policy-spec.md` §10 | `chock check --only index` (`cmd_refresh()` in `src/chock/index/cli.py`, `--check` mode) regenerates `.agents/policies/INDEX.md` and the `AGENTS.md` pointer and exits non-zero on any diff from generated; wired into `chock check` by `lifecycle.py`'s `index` sub-check (`rc = max(rc, _run("index freshness", cmd_refresh, ...))`) | error | The invariant is "the compiled ambient surface is what the policies produce; nobody hand-edits it." This is a repointing (owner decision, `plan/chock-g1/briefs/w5-matrix-vs-code-check.md`), not a redesign: the row previously named `check_ambient_rule_blocks()` as a byte-match, which it has never performed. That function (in `checks_repo.py`) is a secondary, warning-level helper — it checks the `AGENTS.md` pointer text and INDEX.md presence, not a byte-match against `rule.text`, and every one of its findings is `"warning"`, so it structurally cannot fail a build (`Report.ok` is `not self.errors`) | lifecycle |

## Deterministic-first invariants (DET) — Phase 2

| ID | Spec | Check | Severity | Notes | Dispatch |
|---|---|---|---|---|---|
| DET-1 | `spec/policy-spec.md` §11 | `the validator`: `check_scripts_shipped()` — `skill.skill_type: code\|hybrid` requires non-empty `scripts/` with an executable script | error | `scripts.entrypoint` optional for skills but must resolve if present; standalone script artifacts are not allowed | engine |
| DET-2 | `spec/policy-spec.md` §11 | `the registry`: sha256 hashes per script; `the validator`: `check_script_integrity()` verifies for production/verified+ artifacts | error | Stale registry triggers a rescan, not a silent pass | engine |
| DET-3 | `spec/optimization.md` §2 | `optimize` skill: `determinize_edit` edit type; `the validator`: `check_determinization_heuristic()` flags NL skills with regex/command sequences | info | Human review required for `determinize_edit` | engine |
| DET-4 | `spec/policy-spec.md` §12 + `spec/methodology.md` | `src/chock/packs/_skills/policy-init/references/taxonomy.md` requires a pre-walk `determinism_scan` that splits deterministic_parts from judgment_parts; mechanical parts route to a code/hybrid skill with a committed script. `policy-init` eval cases verify the split and routing. | eval | Enforced by eval suite; post-hoc backstop is DET-3 | n/a |

## Effects and approvals (EFF) — Phase 3

| ID | Spec | Check | Severity | Notes | Dispatch |
|---|---|---|---|---|---|
| EFF-1 | `spec/policy-spec.md` §12 + `spec/methodology.md` D1 | Schemas require explicit `effects` for `skill`/`subagent`; `the validator`: `check_effects_and_approval()` requires `enforcement: verify\|block` and `approval: {required: true}` when any effect is `writes_external` or `irreversible` | error | `writes_workspace` triggers git-state capture; `read_only`/`reads_private`/`network` are informational | engine |

## Agent-driven orchestration (ORC)

| ID | Spec | Check | Severity | Notes | Dispatch |
|---|---|---|---|---|---|
| ORC-1 | `spec/policy-spec.md` §13 | `check_composition_contract()`: workflow phases, invocation targets, bounded fan-out, and correlation keys | error | Host agent performs dispatch; validator checks the contract | engine |
| ORC-2 | `spec/policy-spec.md` §13 | `check_composition_contract()`: phase and workflow monitoring are required | error | Missing results route to `needs_handoff` | engine |
| ORC-3 | `spec/policy-spec.md` §13 | `check_composition_contract()` and subagent interface checks require work-item handoff fields | error | Required fields: work_item_id, phase, status, outcome, error | engine |
| ORC-4 | `spec/policy-spec.md` §13 | `check_composition_contract()`: fan-out isolation and human checkpoint approval bindings | error | Write-capable integrations must enforce this at the adapter boundary | engine |
| ORC-5 | `spec/policy-spec.md` §13 | `check_composition_contract()`: workflow name prefix | warning | Default prefix is `Orchestrator /` | engine |

## Interface rigor (INT) — Phase 5

| ID | Spec | Check | Severity | Notes | Dispatch |
|---|---|---|---|---|---|
| INT-1 | `spec/policy-spec.md` §13 | `manifest.common.json`'s `inputSchema` definition requires `additionalProperties: false` and property-level `type`/`description`; `the validator`: `validate_yaml_against_schema()` reports violations | error | Applies to `code` and `hybrid` skill artifacts; `nl` skills are exempt from I/O schemas. `interface.yaml` supplies these schemas when present. | engine |
| INT-2 | `spec/policy-spec.md` §13 | `manifest.common.json`'s `outputSchema` definition requires `properties.outcome` enum containing `[success, failure, needs_handoff]` and `additionalProperties: false`; `the validator`: `validate_yaml_against_schema()` reports violations | error | Applies to `code` and `hybrid` skill artifacts; `nl` skills are exempt. Gives optimizer clean conformance signal. `interface.yaml` supplies these schemas when present. | engine |
| INT-3 | `spec/policy-spec.md` §13 | `the validator`: `check_verb_first_naming()` warns when a draft/sandbox executing artifact ID does not start with a verb | warning | Existing IDs are grandfathered | engine |

## Hermetic execution (HRM) — Phase 5

| ID | Spec | Check | Severity | Notes | Dispatch |
|---|---|---|---|---|---|
| HRM-1 | `spec/policy-spec.md` §14 | Eval-level behavior case per meta-skill (`policy-init`, `validate`, `eval`, `optimize`, `chock-init`) proves configuration is read from the artifact's own folder or `.chock/config.yaml`, not conversation instructions | eval | Not statically checkable; enforced by eval suite | n/a |

## Policy toggles (POL)

| ID | Spec | Check | Severity | Notes | Dispatch |
|---|---|---|---|---|---|
| POL-1 | `spec/policy-spec.md` §17 | `the validator`: `check_policy_toggles()` errors if `policies.disabled` contains a policy with `mandatory: true` | error | CLI `disable` also blocks this with exit code 2 | engine |
| POL-2 | `spec/policy-spec.md` §17 | `the validator`: `check_policy_toggles()` warns on unknown ids in `policies.disabled` or `policies.overrides` | warning | Validates config without crashing on typos | engine |
| POL-3 | `spec/policy-spec.md` §17 | `the validator`: `check_policy_toggles()` warns when `scan-secrets` or `protect-main-branch` is downgraded to advisory | warning | Catch accidental weakening of block guards | engine |

## Operational checks (WRP/TPL/FRS) — Phase 5

| ID | Spec | Check | Severity | Notes | Dispatch |
|---|---|---|---|---|---|
| WRP-1 | `spec/policy-spec.md` §15 | `the validator`: `check_adapter_integrity()` verifies every generated adapter file references `AGENTS.md` | warning | Applies to the 16 adapter files listed in `AGENTS.md` | engine |
| TPL-1 | `spec/policy-spec.md` §15 | Mirrors: `src/chock/packs/_skills/policy-init/assets/templates/**` (recursive) with `.agents/skills/policy-init/assets/templates/**`; keep in sync manually | unautomated | Copy the packaged source to the compiled folder when it changes. No check compares the two trees today; previously labelled `warning`, which nothing could ever emit | n/a |
| FRS-1 | `spec/policy-spec.md` §15 | `the validator`: `check_adapter_integrity()` requires a `fetched_at` or `updated_at` freshness marker and warns if it is older than 30 days | warning | Marker format: `YYYY-MM-DD` in a comment or frontmatter | engine |
| SCH-1 | `spec/policy-spec.md` §15 | `chock install-skills` copies canonical `manifest*.json` schemas from `src/chock/validation/schemas/` into `.agents/skills/validate/assets/`; the validator uses the installed package's own schemas | unautomated | Re-install skills to refresh schemas. The copy is one-way with no drift check; previously labelled `error`, which nothing could ever emit | n/a |
| REL-1 | `spec/policy-spec.md` §15 | `the validator`: `check_release_consistency()` compares `VERSION`, `pyproject.toml`, and the top `CHANGELOG.md` entry | error | Bump all three together in every release | engine |
| AMB-1 | `spec/policy-spec.md` §15 | `the validator`: `check_ambient_token_budget()` estimates tokens across the attention surface in `.agents/policies/INDEX.md` | warning | Soft budget from §4 (`ambient_total_tokens_soft`) | engine |
| AMB-2 | `spec/policy-spec.md` §15 | `the validator`: `check_ambient_conflicts()` parses `.agents/policies/INDEX.md` with provenance and flags direct contradictions, modality conflicts, and scope overlaps between independently authored policies as errors, redundancy as a warning | error | No model call (deterministic set arithmetic); `chock check --only conflicts`; `# chock: conflict-reviewed <key>` suppresses one finding. Only invoked from `checks_conflicts.py`, which `lifecycle.py` imports — `engine.py` never touches it | lifecycle |

## CI traceability checks

- `chock check --only matrix` verifies that every invariant ID in `spec/` appears in this matrix.
- `chock check --only matrix` verifies that every row in this matrix has a non-empty `Check` column.
- `chock check --only mechanisms` verifies that every row naming a `` `function()` `` mechanism has a function that exists in `src/`, is invoked on the `engine` or `lifecycle` dispatch path, and can emit the severity the row claims. Rows whose Severity is `eval`/`unautomated` are skipped, knowingly.
- CI runs these scripts before the validator.
