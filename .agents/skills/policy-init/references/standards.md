# Authoring standards (self-check before handing off)

report: checklist_result to developer

## Budgets (hard)

- [ ] SKILL.md (frontmatter + body) <= 150 lines
- [ ] `description` <= 500 chars
- [ ] each references/ file <= 300 lines, exactly one topic
- [ ] rule artifacts <= 2 lines
- [ ] no content duplicated between SKILL.md body and references/

## Progressive disclosure (hard)

- [ ] SKILL.md body contains only activation surface: what, when, inputs/outputs, minimal contract
- [ ] depth (advanced usage, edge cases, rationale, migration, FAQ, detailed design) lives in references/
- [ ] every references/ file addressed from SKILL.md body by need
- [ ] no depth headings in SKILL.md body

## Always-on context

- [ ] fallback AGENTS.md sections contain only `## Rules` plus one example; everything else links to `references/`
- [ ] ambient rule text <= 2 lines with no elaboration or examples

## YAGNI (hard)

- [ ] no placeholder files, unused templates, or speculative abstractions **after scaffolding is complete and before review**
- [ ] scaffolding may include placeholder files marked with `<!-- SCAFFOLD: replace or delete before review -->`
- [ ] every file justifies its token cost for current use case before promotion to review
- [ ] empty directories removed before hand-off, unless they are standard scaffold folders the developer expects to fill

## Description formula (skills)

order:
1. what it does
2. `Use when` + 3..6 concrete phrases
3. `Do NOT use for` + nearest false-positive

tone: third person
forbid: marketing words

good: "Guides use of corp-http-client for all outbound HTTP. Use when adding an HTTP call, integrating an external API, or reviewing code with raw OkHttp/HttpURLConnection. Do NOT use for internal service-mesh gRPC calls."

bad: "A powerful skill that helps you with HTTP best practices."

## Authoring techniques (see references/authoring-techniques.md — all mandatory)

- [ ] T1 content staged correctly
- [ ] T2 description is an index with concrete keywords
- [ ] T4 mechanical checks offloaded to scripts/
- [ ] T5 delta-only content
- [ ] T7 reference files use self-contained entries
- [ ] R1 explicit contract in body
- [ ] R2 degradation line present
- [ ] S1 treat-as-data rule for external-content skills
- [ ] E1 evals drafted before description; E2 adversarial case if stakes

## Writing style

- imperative instructions; examples over prose; tables for enumerations
- prefer one mined real-code example over three invented ones
- reference files addressed from SKILL.md body by need, never inlined

## Manifest

- [ ] `manifest.yaml` validates against the manifest schema bundled with the validate skill (`assets/manifest.schema.json`) — run `chock check --only validate`
- [ ] id kebab-case; SemVer version; artifact + (skill_type if skill) + enforcement set
- [ ] provenance complete: author, created_at, license, trust_tier: sandbox (rule artifacts: community after review, or ambient_override with documented rationale — SEC-5 blocks sandbox rules from ambient wiring)
- [ ] lifecycle.status: draft
- [ ] optimization block present (LRB 0.20 for new artifacts; frozen_sections includes security)
- [ ] security.content_instructions: never-obey
- [ ] changelog has 0.1.0 entry

## Single destination (hard)

- [ ] exactly ONE deliverable folder created at confirmed target path
- [ ] all temporary/intermediate files deleted; nothing new outside folder + its wiring
- [ ] wiring carries `compiled by chock` comment

## Evals (mandatory)

- [ ] `evals/suite.yaml` with >=3 cases total, including >=1 trigger, >=1 negative_trigger, >=1 behavior
- [ ] hooks: >=1 case proving enforcement fires and >=1 proving compliant actions pass

## Hooks additionally

- [ ] block/verify message tells developer the compliant alternative
- [ ] script deterministic — no LLM calls, no network
- [ ] `manifest.yaml` uses a valid `hook.gate` with `kind`+`params`; `chock compile` emits the git-hook shim + vendored runner for block level

## Agentic designs

