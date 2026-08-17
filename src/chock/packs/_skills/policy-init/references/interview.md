# Interview flow (conversational Initializr)

run_after: classification
ask: structured questions if available (<=4 per batch); else compact prose
skip: already answered questions

## Batch 1 — intent (all artifacts)

1. purpose: one sentence — what should agent do differently once this exists?
2. enforcement: advise / verify / block (propose taxonomy default; apply stakes rule)
3. scope_and_target: repos/languages/paths that apply; deliverable folder location (default: `<repo_root>/generated/`); never generate inside the invoking framework's own `.agents/` or `subagents/` folders; confirm exact output path before writing
4. owner: team or person accountable (manifest + frontmatter)

## Batch 2 — knowledge source (skills; skip pure hooks)

choice:
- Paste it: developer supplies docs/text now
- Point me at files: paths/globs to read
- Let me mine this repo: run extraction below
- combination allowed

### Extraction

when pointed at code:
- grep library/pattern
- read 3..5 most representative call sites
- distill into `examples/` as GOOD examples (verbatim, trimmed, file-path attribution)
- if anti-patterns named, grep those too; record one as BAD example with correction
- real mined examples outrank invented ones

## Batch 3 — activation & correctness (skills)

1. trigger_phrases: 3..6 things developer would actually say to activate this
2. nearest_false_positive: adjacent request that must NOT activate it
3. right_vs_wrong_output: one concrete example of each, or confirm mined examples

## Batch 4 — multi-agent workflow / orchestrator

1. phases: what are the distinct stages? (do NOT assume a fixed set)
2. guardrails: are there preconditions between phases? (e.g. "don't validate until build passes", "block merge without tests green"). Scaffold as companion hooks/rules only if the user describes them; do not inject defaults.
3. parallelism: which phases fan out? what is the fanout key? (e.g. per repository, per artifact)
4. approval: are there approval gates? between which phases? (optional — do not assume yes)

## Batch 5 — hooks only

1. exact_condition: tool/command pattern to match (e.g., `git push` to which branches; file globs for protected paths)
2. failure_message: what developer/agent should do instead
3. escape_hatch: sanctioned override? who may use it?

## Then

1. summarize: classification, enforcement, target path, files to create, owner
2. generate ONE deliverable folder directly at target; status: draft
3. delete temporary files; only deliverable folder + wiring remain
4. self-check against `references/standards.md`; show checklist result
5. hand off: folder created, wiring, fresh-session test instructions; promotion to review happens by PR — a reviewer must be able to replay the evals
