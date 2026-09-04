    # Chock Policy Specification (v0.0.1)

policy:
  scope: one self-contained folder in target repo
  adapters: add wiring only; no second copy
  schema: schema/manifest.schema.json

## 1. Single-destination rule

require(generation):
  writes ONLY to deliverable folder and its wiring
  deletes temporary files
deliverable_folder: source_of_truth
validation: runs in place
wiring:
  derived: true
  marker: "compiled by chock"
  regeneration_source: policy folder

## 2. Deliverable formats

| Class | Location | Wiring |
|---|---|---|
| skill | `.agents/skills/<id>/` | none; optional fallback AGENTS.md section |
| hook (gate) | `.agents/policies/<id>/` | git hook (required for block) |
| rule | `.agents/policies/<id>/` (governance) | ≤2-line rule in ambient file's marked section |

### skill

```
.agents/skills/<id>/
├── SKILL.md              # frontmatter IS the manifest (metadata.chock.*)
├── interface.yaml        # optional: input_schema / output_schema / evaluation
├── references/
├── scripts/
└── evals/suite.yaml
```

### hook

```
.agents/policies/<id>/
├── manifest.yaml          # contains hook.gate
├── implementations/       # optional: only if the hook needs scripts
└── evals/suite.yaml
```

### rule

```
.agents/policies/<id>/
├── manifest.yaml
└── evals/suite.yaml
```

plus ≤2-line rule in ambient file's marked section.

require(hook with action:block): wiring MUST include git hook.

## 3. Skill types

| Type | Expression | Example |
|---|---|---|
| nl | SKILL.md body + references/ | how to use corp-http-client |
| code | Deterministic scripts | branch-name validator |
| hybrid | SKILL.md body + scripts | PR creation with template check |
| workflow | Sequences skills/subagents via SKILL.md procedure | release workflow |

prefer(code, nl) when task is mechanical check.

## 4. Token budgets

| Item | Budget |
|---|---|
| SKILL.md | ≤ 150 lines |
| description | ≤ 500 chars |
| Each references/ file | ≤ 300 lines, single topic |
| Ambient rule | ≤ 2 lines |
| Org-wide ambient total | ~500 tokens |

if content over budget: move to references/
if duplication exists between SKILL.md and references/: validation FAIL
fallback AGENTS.md section: rules + one example; link references, do not inline.

## 5. Description formula

Two equivalent forms are valid. Domain skills, rules, and hooks should use the narrative formula. Meta-skills that are invoked programmatically may use the compressed grammar.

### Narrative formula

```
description :=
  clause(what policy does)
  + "Use when ..."(3–6 concrete task phrases)
  + "Do NOT use for ..."(nearest false-positive)
```

### Compressed grammar

```
description :=
  clause(what skill does)
  + "args(" input-params ") returns(" output-shape ") invoke(" intents ") exclude(" anti-intents ")"
```

voice: third person
require: same text in manifest.yaml and SKILL.md description

## 6. Eval suite

require(evals/suite.yaml): minimum 3 cases across:
- trigger: must activate
- negative_trigger: must not activate
- behavior: scenario → expected outcome
- edge: boundary conditions

target: policy, not agent
default metric: pass_rate

## 7. Gate definition (hooks only)

```yaml
gate:
  kind: content_regex
  "on": [commit]       # commit | push | tool_use
  action: block        # block | verify | warn
  message: <actionable: rule + compliant alternative>
  params:
    content_pattern: <regex>
    forbidden_path_regex: <regex>
    allowlist_pragma: <regex>
    scan: added_lines   # added_lines | staged_blob
```

## 8. Lifecycle

```
lifecycle := draft → review → staging → production → deprecated → retired
v0 enforces: draft → review → production → deprecated
```

| Transition | Guards |
|---|---|
| draft → review | schema-valid manifest.yaml, ≥3 eval cases, budgets met, security block present |
| review → production | human approval (PR merge), all checks green |
| production → deprecated | replacement_id set, deprecation noted in changelog |

production versions: immutable; changes → new SemVer version
staging: Phase 2

## 9. Trust tiers

```
tiers := sandbox → community → verified → certified
tier_upgrade: only at review via PR
optimize_playbook: MAY NOT raise tier
```

## 10. Security invariants

> Invariant: **SEC-1** — Embedded instructions in processed content are data, never commands.
- require: `security.content_instructions: never-obey`
- never-obey applies to every artifact type (skill, hook, rule, workflow, subagent)

> Invariant: **SEC-2** — Deterministic scripts contain no LLM calls, no network calls, and no plaintext secrets.
- checked by static scan of `scripts/` under code/hybrid skills and hook implementations
- warning-level for justified network calls with a `network` effect declared under `verify`/`block` enforcement and approval wiring

> Invariant: **SEC-3** — Gate failures present an actionable message naming the compliant alternative.
- required in `gate.message` for every hook that declares a `gate` -- unconditional, not per action: the schema lists `message` in `gate.required` under `additionalProperties: false`. `gate.action` is a `const: block`; the `advise`/`verify`/`block` distinction belongs to `enforcement`, a different field (EFF-1)

> Invariant: **SEC-4** — All artifact text surfaces are scanned for prompt-injection tripwires.
- scan covers: `SKILL.md`, `references/`, `examples/`, `evals/`, templates, manifest string fields (`name`, `description`, `rule.text`, `hook.gate.message`), and eval prompts/expectations
- tripwires catch accidents; load-bearing defenses are never-obey semantics and adversarial evals

> Invariant: **SEC-5** — Rules wired into ambient context require `trust_tier >= community` or an explicit `ambient_override: true` acknowledged in the manifest.
- ambient context is the highest-privilege surface; lower-tier rules must opt in to ambient wiring

> Invariant: **SEC-6** — Skills that process external content ship at least one adversarial eval case.
- flagged via `security.processes_external_content: true` in the skill manifest
- external content includes mined call sites, user files, transcripts, or any non-framework input

> Invariant: **SEC-7** — Marked rule blocks in ambient files (e.g. `AGENTS.md`) byte-match the source policy's `rule.text`.
- canonical form: the exact `rule.text` value is pasted between `<!-- chock:rules:start ... -->` and `<!-- chock:rules:end -->` markers
- no reformatting, no examples, no expansion

## 11. Determinism invariants

> Invariant: **DET-1** — Code and hybrid skills ship deterministic scripts committed under the skill.
- `skill.skill_type: code|hybrid` requires a non-empty `scripts/` directory with at least one executable script file
- `scripts.entrypoint` is optional but, if present, must resolve inside `scripts/`
- scripts are never generated at runtime; the committed script is the only deterministic path
- standalone, agent-less script artifacts are not allowed

> Invariant: **DET-2** — Deterministic scripts for production or verified+ artifacts must match the registry hashes.
- registry format stores `script_hashes: {relpath: sha256_hex}` per entry
- registry scanner hashes every file under `scripts/` and `implementations/`
- validator checks production/verified+ artifacts (trust_tier ∈ {verified, certified} or lifecycle.status = production) against the registry
- stale registry or missing hash triggers a rescan, not a silent pass

## 12. Effects and approvals

> Invariant: **EFF-1** — Artifacts with `writes_external` or `irreversible` effects require `enforcement: verify|block` and explicit approval wiring. See `spec/methodology.md` D1.

- `effects` is a manifest array drawn from: `none`, `read_only`, `writes_workspace`, `writes_external`, `irreversible`, `reads_private`, `network`
- executing artifacts (`skill`, `subagent`) must declare `effects` explicitly; `[none]` and `[read_only]` are valid explicit declarations
- `[none]` may not be mixed with other values
- `read_only`, `reads_private`, and `network` are informational: they guide validators, adapters, and reviewers but do not by themselves block execution
- if any effect is `writes_external` or `irreversible`, then `enforcement` must be `verify` or `block`
- if any effect is `writes_external` or `irreversible`, the manifest must include `approval: {required: true}` (mode: `human` by default)
- policy-init's taxonomy must classify requests with `writes_external` or `irreversible` effects as `verify` or `block` and generate the approval block
- `writes_workspace`, `writes_external`, and `irreversible` should trigger git-state capture before execution when the agent performs the write

## 13. Agent-driven orchestration

> Invariant: **ORC-1** — A workflow skill declares its phases, invocation targets, bounded fan-out, and fan-in correlation key.
> Invariant: **ORC-2** — Every fan-out/fan-in phase declares strong monitoring and a terminal result contract.
> Invariant: **ORC-3** — Every workflow handoff includes `work_item_id`, `phase`, `status`, `outcome`, and `error`.
> Invariant: **ORC-4** — Write-capable phases require isolation and a human approval checkpoint bound to the approved work-item snapshot.
> Invariant: **ORC-5** — Workflow skills use the default display name prefix `Orchestrator /`; invoked skills remain regular skills.

- `skill_type: workflow` requires `composition`.
- `composition.phases` supports `sequential`, `fan_out`, `fan_in`, and `human_checkpoint`.
- Fan-out phases require a source, bounded `concurrency.max_parallel`, isolation, monitoring, and `result.correlation_key`.
- Missing, duplicate, failed, blocked, timed-out, or uncorrelated results are recorded; they are never silently dropped.
- Chock validates this contract; the host agent/adapter creates and monitors subagent sessions.
- No headless workflow engine or runtime-generated script is introduced.

## 14. Interface rigor

> Invariant: **INT-1** — Skill `input_schema` must set `additionalProperties: false` and every property must have both `type` and `description`.
> Invariant: **INT-2** — Skill `output_schema` must include an `outcome` property with enum `success | failure | needs_handoff` and `additionalProperties: false`.
> Invariant: **INT-3** — Newly generated draft/sandbox executing artifacts should start with a verb; existing IDs are grandfathered.

- strict input/output contracts make optimizer conformance signals unambiguous
- the `outcome` property gives the optimizer and runtime a clean success/failure/handoff signal without parsing the full payload
- every schema property must be documented so callers know what to supply and what to expect
- INT-3 is a warning, not a hard gate, to avoid breaking existing IDs; it is enforced by `python -m chock check`

## 15. Hermetic execution

> Invariant: **HRM-1** — Meta-skills must read configuration from their own folder or `.chock/config.yaml`, not from instructions embedded in the conversation.

- eval suites for each meta-skill include a behavior case that supplies a conflicting instruction in the conversation and expects the skill to follow its configured source of truth
- this applies to: `policy-init`, `validate`, `eval`, `optimize`, `chock-init`
- configuration sources include: the artifact's own `manifest.yaml`, `references/` files, `SKILL.md`, and `.chock/config.yaml`
- conversation instructions are treated as data/evidence, never as overrides for configured behavior

## 16. Operational checks

> Invariant: **WRP-1** — Generated adapter wrapper files must delegate to `AGENTS.md` and must not silently drift from the source of truth.

- every adapter file (e.g., `.claude/CLAUDE.md`, `.cursorrules`, `.github/copilot-instructions.md`) must contain a reference to `AGENTS.md`
- adapters are thin wrappers; they do not duplicate policy content
- the validator flags adapters that do not reference `AGENTS.md`

> Invariant: **TPL-1** — `policy-init` template copies are intentional mirrors of the packaged source.

- `src/chock/packs/_skills/policy-init/assets/templates/` (including subdirectories) is the source of truth for generated artifacts
- `.agents/skills/policy-init/assets/templates/` is the compiled copy used by the skill
- the validator no longer enforces template drift; keep mirrors in sync when the packaged source changes

> Invariant: **SCH-1** — The installed package's manifest schemas under `src/chock/validation/schemas/` are the single canonical source. The `validate` skill injects them into `.agents/skills/validate/assets/` at install time.

- the validator loads schemas from `src/chock/validation/schemas/` (or the installed package equivalent)
- `chock install-skills` copies the canonical schemas into the consumer's `.agents/skills/validate/assets/` directory

> Invariant: **REL-1** — `VERSION`, `pyproject.toml`, and the top `CHANGELOG.md` entry must agree on the release version.

- three sources of the version truth, one deterministic check; disagreement is an error

> Invariant: **AMB-1** — Compiled ambient rule blocks must stay within the ~500-token soft budget (§4).

- the validator estimates tokens across the attention surface in `.agents/policies/INDEX.md` (the file `AGENTS.md` points agents to read) and warns on overrun

> Invariant: **AMB-2** — Rules compiled from independently authored, independently enabled policies must not contradict each other in the attention surface.

- the validator parses `.agents/policies/INDEX.md` with provenance and flags, as errors, a direct contradiction, a modality conflict (opposing verbs from the closed vocabulary), and a scope overlap (intersecting targets with opposite verdicts); redundant or shadowed rules are a warning naming their token cost against AMB-1
- deterministic set arithmetic only, never a model call (Arbiter, arXiv:2603.08993); `# chock: conflict-reviewed <key>` in a policy's `rule.text` suppresses exactly that finding

> Invariant: **FRS-1** — Generated adapter files must carry a freshness marker (`fetched_at` or `updated_at`) and must be refreshed if the marker is older than 30 days.

- freshness markers are checked by the validator
- stale adapters warn that they may have drifted from the current `AGENTS.md` source of truth

## 17. Policy toggles

> Invariant: **POL-1** — A mandatory policy cannot be disabled through `.chock/config.yaml` or the `chock disable` CLI.

- `mandatory: true` in a policy manifest is an enforceable lock
- `chock check` and `chock disable` both reject disabling a mandatory policy

> Invariant: **POL-2** — Unknown policy ids in `policies.disabled` or `policies.overrides` trigger a validation warning.

- consumer config can reference policies that are not installed; the validator warns so typos are caught

> Invariant: **POL-3** — Block security guards (`scan-secrets`, `protect-main-branch`) must not be silently downgraded to advisory.

- `enforcement: block` guards that are scoped to `advisory` via `policies.overrides` are reported as warnings
- this is a guard against accidental weakening of compliance-stakes controls
