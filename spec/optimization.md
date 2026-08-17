# Chock Optimization Strategy (SkillOpt)

optimize_playbook:
  purpose: improve policies from evidence
  constraint: strict safety bounds

## 1. The loop

```
loop :=
  trace_collection
  → quality_filtering
  → bounded_edit_proposal
  → validation_gate
  → promote_or_reject
  → rejected_edit_buffer
```

### Step 1 — Trace collection

evidence: {session_transcripts, eval_results, reported_misses}
require: ≥3 traces before edit proposal
V0: manual collection
automated collection: Phase 2

### Step 2 — Quality filtering

split traces on:
  - activation: did fire when should? stay silent when shouldn't?
  - conformance: was output compliant?

### Step 3 — Bounded edit proposal

rule: one edit per cycle
targets: SKILL.md body | references/ | description

constraints:
  - learning_rate_budget (LRB): edit_distance_ratio ≤ manifest.yaml budget (default 0.10)
  - frozen_sections: never modified
  - prompt_edit, example_edit: self-serve
  - determinize_edit (convert regex/command heuristics into committed scripts): requires human review
  - structural_edit (files, skill_type, enforcement level): requires human review
  - each proposal records rationale, expected improvement, trace IDs

| Artifact maturity | LRB |
|---|---|
| < 1 month in production | 0.20 |
| 1–6 months | 0.10 (default) |
| > 6 months, stable | 0.05 |
| certified tier | 0.02 |

### Step 4 — Validation gate

action: re-run eval suite against candidate

| Mode | Rule |
|---|---|
| strict | every metric improves |
| standard (default) | primary metric improves ≥ 1 point of pass_rate; secondaries within −5%; floor min_eval_score applies |
| permissive | advisory only |

### Step 5 — Promote or reject

if promoted:
  apply edit
  bump patch version
  append changelog entry
if rejected:
  store in buffer

### Step 6 — Rejected-edit buffer

path: `rejected-edits/<date>-<slug>.md`
contents: {proposed_diff, eval_results, reason_for_failure}
retention: 90 days
future_runs: read buffer first
re-propose previously rejected idea: require new evidence
human override: via PR; reason goes in changelog

## 2. Invariants

> Invariant: **DET-3** — NL skills that contain regex or command-sequence heuristics are flagged as determinization candidates; converting them to committed scripts requires human review.
- heuristic is info-level; the optimizer may suggest a `determinize_edit` but may NOT apply it autonomously
- `determinize_edit` must create or update `scripts/` and set `skill_type: hybrid|code`; the resulting script must pass the same eval gate
- structural changes and runtime-effect changes remain human-owned

- optimizer proposes; humans own promotion boundaries
- optimizer may NOT change: lifecycle status, trust tier, enforcement level, security blocks
- one edit per cycle
- code hooks: optimize only via eval suites; docs/messages may change, enforcement logic requires human review

## 3. Run record

every run appends to `optimization-log.yaml` beside artifact:

```yaml
run_at:
traces_used:
proposal_summary:
lrb_used:
gate_mode:
gate_result:
outcome:
new_version:
```
