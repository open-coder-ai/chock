# SkillOpt bounds and gate logic

this_file: operational bounds and gate logic executed by the `optimize` skill (evidence-gated, budget-bounded self-improvement)

## Edit types

| Type | Examples | Self-serve? |
|---|---|---|
| prompt_edit | reword SKILL.md body instructions, sharpen description trigger phrases | yes, within LRB |
| example_edit | add/replace example (prefer newly mined real code) | yes, within LRB |
| determinize_edit | convert regex/command-sequence heuristics into a committed deterministic script under a code/hybrid skill | no — flag for human PR |
| structural_edit | add/remove files, change skill_type, change enforcement | no — flag for human PR |

all edits must preserve authoring techniques (the policy-init skill's `references/authoring-techniques.md`):
- reject: inlines reference content into body
- reject: replaces script with prose
- reject: adds non-delta textbook content
- determinize_edit must create or update `scripts/` and set `skill_type: hybrid|code`; never leave an ad-hoc regex in prose

## Learning-rate budget (LRB)

```
lrb_used = levenshtein(original_text, proposed_text) / len(original_text)
require lrb_used <= policy.optimization.learning_rate_budget
```

- compute per edited file
- v0 estimate: changed_characters / total_characters is acceptable; state estimate in proposal
- if fix exceeds budget, propose largest within-budget step and say so

## Frozen sections

- match `manifest.yaml` `optimization.frozen_sections` against markdown headings and file paths
- security comment line and `security:` block are always implicitly frozen

## Validation gate

- baseline: last recorded eval results (`optimization-log.yaml` or fresh pre-edit run)
- candidate: suite re-run after applying edit in scratch copy
- strict: every metric improves or holds; any regression blocks
- standard: primary metric (pass_rate) improves by >= 0.01 absolute; secondaries within -5% relative; candidate primary >= min_eval_score always
- permissive: advisory — record results, promote anyway (sandbox drafts only)

## Records

`optimization-log.yaml` (append):
```yaml
- run_at: ISO_8601
  traces_used: [T1, T2, T3]
  proposal: one-line summary
  edit_type: prompt_edit
  lrb_used: 0.07
  gate: {mode: standard, baseline: 0.75, candidate: 0.90, result: pass}
  outcome: promoted        # promoted | rejected
  new_version: 0.1.1       # when promoted
```

`rejected-edits/<yyyy-mm-dd>-<slug>.md`:
- proposed diff
- eval results
- gate failure reason
- motivating traces
- TTL 90 days (note expiry date in file)
- human override via PR; override reason goes into artifact changelog
