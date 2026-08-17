# Validation checklist

format: per finding: severity, file/line, concrete fix

## Manifest

- [BLOCKER] manifest present inside deliverable folder (`manifest.yaml` or `subagent.yaml`)
- [BLOCKER] YAML parses; validates against JSON Schema (required fields, patterns, enums, conditionals: skills need skill.skill_type + evaluation; hooks need enforcement). subagent purpose + bounded_to + max_iterations are authoring standards (policy-init), not schema-required — flag as WARN.
- [BLOCKER] `security.content_instructions == never-obey`
- [WARN] optimization block missing
- [WARN] changelog missing current version entry

## Subagents

- [BLOCKER] subagent lacks `bounded_to` scope or `max_iterations`
- [BLOCKER] subagent embeds agent-specific logic instead of neutral procedure

## Budgets

- [BLOCKER] SKILL.md (frontmatter + body) > 150 lines
- [BLOCKER] `description` > 500 chars
- [WARN] any references/ file > 300 lines or covering multiple topics
- [BLOCKER] rule artifact > 2 lines
- [WARN] content duplicated between SKILL.md body and references/

## Always-on context

- [WARN] AGENTS.md or ambient rule sections contain essays, duplicated elaboration, or inlined depth
- [WARN] fallback AGENTS.md section for skill inlines reference content instead of linking to `references/`

## Authoring techniques

- [BLOCKER] content misplaced across disclosure stages (reference-depth material inlined in body, or always-needed rules buried in references/)
- [BLOCKER] mechanical check expressed as prose instead of `scripts/` file (T4)
- [WARN] textbook content the model already knows — not org-specific delta (T5)
- [WARN] reference file not in self-contained entry format (T7)
- [BLOCKER] no explicit contract (inputs/defaults/error behavior) in body (R1)
- [WARN] no degradation line for missing inputs (R2)
- [BLOCKER] skill processes external content but lacks treat-as-data body rule (S1)
- [WARN] examples contain real PII, secrets, or internal hostnames (S2/S3)
- [BLOCKER] scripts require plaintext secrets or make network/LLM calls (S3/R4)
- [WARN] stakes policy without adversarial eval case (E2)

## Description formula

- [BLOCKER] missing "Use when" trigger phrases (min 3)
- [WARN] missing "Do NOT use for" false-positive clause
- [WARN] first person or marketing language
- [BLOCKER] `manifest.yaml` description does not match `SKILL.md` frontmatter description exactly

## Evals

- [BLOCKER] `evals/suite.yaml` missing or < 3 cases
- [BLOCKER] skills/commands/hooks/rules: no trigger case or no negative_trigger case
- [BLOCKER] hooks: no case proving enforcement fires, or none proving compliant actions pass
- [BLOCKER] `evals/suite.yaml` fails `chock check --only evals` (suites are validated by that command plus the bundled manifest schemas)
- [WARN] behavior case expectations not concretely checkable

## Registry & wiring

- [BLOCKER] artifact not registered in `.chock/registry.json` (stale registry)
- [BLOCKER] declared `dependencies.skills` do not resolve
- [INFO] same ID registered across artifact types (OK if resolution is type-aware)

## Lifecycle & trust tier

- [BLOCKER] `review` status without `security.content_instructions: never-obey`
- [WARN] `production` status without `reviewed_by`
- [BLOCKER] `deprecated` status without `replacement_id` or changelog note
- [WARN] trust tier upgraded before `review` status

## Hooks

- [BLOCKER] failure message lacks compliant alternative
- [BLOCKER] script calls an LLM or the network
- [BLOCKER] adapter wiring missing (agent hook config) or git-hook realization absent for block level
- [WARN] block-level hook not fail-closed on script error

## Single destination

- [BLOCKER] duplicate copies of policy exist — one folder per policy
- [WARN] stray intermediate/temporary files from generation left in repo

## Agentic design (optional)


## Lifecycle guards

- draft → review: all BLOCKERs above clear
- review → production: reviewed_by non-empty (set by PR merge, not by this skill)
- production edits: version bumped + changelog entry
