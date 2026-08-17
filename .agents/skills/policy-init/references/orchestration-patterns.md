# Orchestration patterns

Advanced patterns for workflow skill orchestrators. These are optional — scaffold them only when the user's request warrants them.

## Failure handling

### failure_policy selection

| Policy | Use when | Behavior |
|---|---|---|
| `stop` | Any failure is fatal to the workflow | Abort remaining phases; handoff with error |
| `continue_and_record` | Partial results are useful (e.g. review N repos, some may fail) | Record failure per item; continue others |
| `retry_then_record` | Transient failures expected (network, rate limits) | Retry up to `runtime.max_retries`; record if still failing |

### Partial failure in fan-out

When `failure_policy: continue_and_record`, the fan-in phase receives a mix of succeeded and failed items. The consolidation skill must:

1. Separate results by outcome: `success` vs `failure` vs `needs_handoff`.
2. Include per-item error details in the handoff report.
3. Set the orchestrator outcome to `needs_handoff` if any item failed, `success` only if all succeeded.

```yaml
# fan-in phase handling partial failures
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
```

## Timeout escalation

When a phase's `monitoring.timeout` fires:

1. The runtime marks the phase as `failure` with error `"timeout after <duration>"`.
2. `failure_policy` determines next action: `stop` aborts the workflow; `continue_and_record` marks timed-out items as failed and continues.
3. The handoff report includes timed-out items with their last known status.

Timeout values should reflect the actual work: code review ~10-30m, build/test ~30-60m, human approval ~24h.

## Checkpoint / resume

For long-running workflows (>10 phases, >1h total), scaffold a `.workflow-state.yaml` convention:

```yaml
# .workflow-state.yaml (written by orchestrator SKILL.md, not manifest.yaml)
workflow_id: "<orchestrator-id>-<timestamp>"
current_phase: "transform"
completed_phases:
  - id: prepare
    outcome: success
    completed_at: "2026-07-12T10:30:00Z"
pending_items:
  - work_item_id: "item-3"
    last_status: "in_progress"
```

The orchestrator SKILL.md procedure should:

1. On start: check for `.workflow-state.yaml`; if found, resume from `current_phase`.
2. After each phase: write updated state.
3. On completion: remove the state file.

This is a SKILL.md-level convention, not a schema feature. Scaffold it as a reference doc when the workflow is long-running.

## Progress reporting

The orchestrator SKILL.md should surface per-item status during execution. Use the 5 mandatory monitoring fields:

```text
Phase: process [3/10] | success: 2, failure: 1, pending: 7
Phase: consolidate [0/1] | waiting for process completion
```

The `monitoring.progress_fields: [work_item_id, phase, status, outcome, error]` declaration tells the runtime which fields to track. The orchestrator SKILL.md maps these to human-readable summaries.

## Rollback / compensating actions

When a workflow includes `writes_external` or `irreversible` effects and a later phase fails:

1. The orchestrator should declare a `rollback` section in its SKILL.md (not in manifest.yaml).
2. Each phase with side effects documents its compensating action.

```markdown
## Rollback

If the workflow fails after the `deploy` phase:
1. `deploy` → revert: `git revert <commit>` + redeploy previous version
2. `notify` → revert: send correction notification

Rollback is manual unless the skill explicitly automates it.
```

Scaffold this pattern when the user describes irreversible multi-step workflows. The rollback is documented in SKILL.md, not enforced by schema.

## Dry-run / preview mode

When the workflow has side effects, offer a `dry_run` input property:

```yaml
input_schema:
  type: object
  additionalProperties: false
  properties:
    work_items:
      type: array
      description: "Items to process."
      items:
        type: object
    dry_run:
      type: boolean
      description: "When true, simulate all phases without writing. Reports what would change."
  required: [work_items]
```

The orchestrator SKILL.md checks `dry_run` and skips phases with `writes_workspace`, `writes_external`, or `irreversible` effects, reporting planned actions instead. The `effects` declaration stays the same (it reflects the non-dry-run path).

## Incremental / watch mode

For workflows that process deltas (e.g. "review only changed files since last run"):

1. Add a `since` or `baseline` input property.
2. The first phase filters work items against the baseline.
3. Store the high-water mark in `.workflow-state.yaml` for subsequent runs.

```yaml
input_schema:
  type: object
  additionalProperties: false
  properties:
    work_items:
      type: array
      description: "All candidate items."
      items:
        type: object
    since:
      type: string
      description: "ISO 8601 timestamp or git ref. Process only items changed after this point."
  required: [work_items]
```

This is a SKILL.md-level convention. The orchestrator procedure filters the item list before entering the fan-out phase, not during.
