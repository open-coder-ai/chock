# Multi-agent workflow scaffold

When `policy-init` classifies a request as a **multi-agent workflow / orchestrator**, it scaffolds a family of related artifacts. The number of phases, skills, and subagents is driven by the user's request — not hardcoded. Every inner skill and subagent gets the same complete folder structure as its class (see `references/scaffold-layout.md`).

## Folder layout

```text
<target>/
├── .agents/skills/<orchestrator-id>/    # workflow skill
│   ├── manifest.yaml, SKILL.md, evals/suite.yaml
│   ├── examples/README.md, assets/.gitkeep
├── .agents/skills/<phase-N-skill-id>/   # one per phase
│   └── (same structure as above)
└── subagents/<phase-N-subagent-id>/     # one per phase needing isolation
    ├── subagent.yaml, evals/suite.yaml, references/
```

Generate as many skill + subagent pairs as the workflow requires. Do NOT default to a fixed set.

When the user describes guardrails, also scaffold companion policies (see **Companion policies** below).

## Companion policies (optional)

Scaffold only when the user describes phase-transition preconditions or mechanical guardrails. Do NOT inject by default.

**Hook** — mechanically verifiable (CI status, test results, checksums); `enforcement: block` or `verify` with `implementations/` script.
**Rule** — guideline agents should follow; `enforcement: advise` or `verify` as ambient rule.

| User says | Scaffold as | ID example |
|---|---|---|
| "don't validate until build passes" | hook (block) | `require-green-build` |
| "block merge if security scan has criticals" | hook (block) | `block-critical-security` |
| "always run lint before opening PR" | hook (verify) | `pre-pr-lint-check` |
| "prefer small PRs over large ones" | rule (advise) | `prefer-small-prs` |

```text
└── .agents/policies/<guardrail-id>/
    ├── manifest.yaml (with hook.gate for hooks), evals/suite.yaml
    ├── implementations/<gate>.sh (hooks only), references/
```

The orchestrator SKILL.md references companion policies in its `## Rules` section. Companion policies are enforced independently — they are NOT listed in `dependencies`.

## Path construction

Always use OS-aware path join. Never concatenate raw strings.

- Python: `Path(target) / ".agents" / "skills" / id`
- Node: `path.join(target, ".agents", "skills", id)`

## Orchestrator dependencies

List only the skills and subagents the workflow actually uses:

```yaml
dependencies:
  skills:
    - id: <phase-1-skill-id>
    - id: <phase-2-skill-id>
  subagents:
    - id: <phase-1-subagent-id>
    - id: <phase-2-subagent-id>
```

## Composition block (orchestrator manifest.yaml)

The `composition` section is **required** for workflow skills and must include `phases`, `monitoring`, and `handoff`. Each phase must include its own `monitoring` block.

### Invocation model

Phases use `invoke.skill` to invoke inner skills directly. Subagents define the isolation/execution contract but are NOT the invocation target — the subagent's `delegates.skill` + `execution_scope` tells the runtime HOW to run it.

### Phases are request-driven

- Derive phases from the user's request. No fixed template.
- Approval gates (`human_checkpoint`) are **optional** — only when explicitly requested or when effects require them (`writes_external` or `irreversible`).

### Handoff contract (mandatory 5 fields)

Every `handoff.required_fields` MUST include all five: `[work_item_id, phase, status, outcome, error]`. These are the minimum; add domain-specific fields after.

### Phase data flow

- `source` wires a phase's input: `input.<field>` reads from orchestrator input; `<phase_id>.results` or `<phase_id>.result` reads from a prior phase's output.
- `result.correlation_key` ties fan-out results to their input items; the subagent's `output_schema` must include this field.
- `result.schema_ref` optionally references a JSON schema file for per-item result validation.

### Phase mode enum

Use only: `sequential`, `fan_out`, `fan_in`, `human_checkpoint`. Never use `parallel` (not in schema).

### Fan-out requirements (ORC-1, ORC-4)

Every `fan_out` phase MUST include: `source`, `isolation` (with `required: true`, `boundary`, `checkout`), `concurrency.max_parallel`, `result.correlation_key`.

### Example: fan-out → fan-in (no approval)

```yaml
composition:
  pattern: fan-out-fan-in
  phases:
    - id: process
      mode: fan_out
      source: input.work_items
      invoke:
        skill: <processing-skill-id>
      isolation:
        required: true
        boundary: assigned_work_item
        checkout: isolated
      concurrency:
        max_parallel: 10
      failure_policy: continue_and_record
      result:
        correlation_key: work_item_id
        schema_ref: references/item-result.schema.json
      monitoring:
        required: true
        heartbeat: per_item
        timeout: "30m"
        terminal_states: [success, failure, needs_handoff]
    - id: consolidate
      mode: fan_in
      source: process.results
      failure_policy: continue_and_record
      result:
        correlation_key: work_item_id
      monitoring:
        required: true
        heartbeat: per_phase
        timeout: "5m"
        terminal_states: [success, failure, needs_handoff]
  monitoring:
    required: true
    progress_fields: [work_item_id, phase, status, outcome, error]
    on_missing_result: needs_handoff
  handoff:
    required: true
    required_fields: [work_item_id, phase, status, outcome, error]
    on_failure: needs_handoff
```

### Example: staged with approval gates

```yaml
composition:
  pattern: approval-gated-parallel
  phases:
    - id: analysis
      mode: fan_out
      source: input.repositories
      invoke:
        skill: <analysis-skill-id>
      isolation:
        required: true
        boundary: assigned_repository
        checkout: isolated
      concurrency:
        max_parallel: 10
      failure_policy: stop
      result:
        correlation_key: repository
      monitoring:
        required: true
        heartbeat: per_item
        timeout: "30m"
        terminal_states: [success, failure, needs_handoff]
    - id: analysis_approval
      mode: human_checkpoint
      source: analysis.results
      approval:
        required: true
        binds_to: [analysis.results]
      failure_policy: stop
      monitoring:
        required: true
        heartbeat: per_phase
        timeout: "24h"
        terminal_states: [approved, rejected]
    - id: execution
      mode: fan_out
      source: analysis_approval.result
      invoke:
        skill: <execution-skill-id>
      isolation:
        required: true
        boundary: assigned_repository
        checkout: isolated
      concurrency:
        max_parallel: 10
      failure_policy: stop
      result:
        correlation_key: repository
      monitoring:
        required: true
        heartbeat: per_item
        timeout: "1h"
        terminal_states: [success, failure, needs_handoff]
    - id: collect
      mode: fan_in
      source: execution.results
      failure_policy: continue_and_record
      result:
        correlation_key: repository
      monitoring:
        required: true
        heartbeat: per_phase
        timeout: "5m"
        terminal_states: [success, failure, needs_handoff]
  monitoring:
    required: true
    progress_fields: [work_item_id, phase, status, outcome, error]
    on_missing_result: needs_handoff
  handoff:
    required: true
    required_fields: [work_item_id, phase, status, outcome, error, analysis_report, execution_report]
    on_failure: needs_handoff
```

### Example: sequential pipeline

```yaml
composition:
  pattern: sequential-pipeline
  phases:
    - id: prepare
      mode: sequential
      invoke:
        skill: <prepare-skill-id>
      failure_policy: stop
      monitoring:
        required: true
        heartbeat: per_phase
        timeout: "10m"
        terminal_states: [success, failure, needs_handoff]
    - id: transform
      mode: sequential
      source: prepare.result
      invoke:
        skill: <transform-skill-id>
      failure_policy: stop
      monitoring:
        required: true
        heartbeat: per_phase
        timeout: "30m"
        terminal_states: [success, failure, needs_handoff]
  monitoring:
    required: true
    progress_fields: [work_item_id, phase, status, outcome, error]
    on_missing_result: needs_handoff
  handoff:
    required: true
    required_fields: [work_item_id, phase, status, outcome, error]
    on_failure: needs_handoff
```

## Subagent delegation

Every workflow subagent must declare `effects` >= the delegated skill's effects. Every subagent `output_schema` must include handoff fields `work_item_id`, `phase`, `status`, `outcome`, and `error` as required properties.

```yaml
delegates:
  skill: <corresponding-skill-id>
execution_scope:
  input_key: work_item
  repository_key: repository
  isolation:
    required: true
    boundary: assigned_work_item
```

## Naming

- Orchestrator: `Orchestrator / <Pattern Name>`
- Inner skills: regular names; no `Orchestrator /` prefix
- Subagents: scoped names ending in the phase role, e.g. `repo-analysis-agent`
