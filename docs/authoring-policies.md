# Authoring Policies

A policy is a small folder under `.agents/policies/<id>/`. Scaffold one with
`chock new policy <id>`, then fill it in. This guide covers the manifest and the four artifact
types you'll write most.

## Anatomy of a policy folder

```text
.agents/policies/block-console-log/
├── manifest.yaml            # manifest — always present
└── evals/
    └── suite.yaml         # trigger / negative / behavior / adversarial cases
```

## The manifest (`manifest.yaml`)

```yaml
id: block-console-log                 # unique, kebab-case
name: "No console.log in commits"
version: "0.1.0"
artifact: hook                     # rule | hook | skill | workflow
enforcement: block                 # advise | verify | block
effects: [read_only]               # guards inspect; they never mutate
description: >
  Block staged JS/TS changes that add console.log.

provenance:
  author: "you"
  license: "Apache-2.0"
  trust_tier: "community"          # sandbox | community | verified
lifecycle:
  status: draft                    # draft → review → production → deprecated
```

The `id` must match `^[a-z][a-z0-9-]{2,63}$` **and** equal its folder name — enforced at
compile and `add`, so path-like ids are rejected.

**Key fields**

- `enforcement` — how strict: `advise` (guidance), `verify` (check, warn), `block` (deny).
- `effects` — what it does to the world. A guard is `read_only`; other values are
  `writes_workspace`, `writes_external`, `irreversible`.
- `approval` — set `required: true` only for *actions* that need a human, never for a read-only guard.

## Artifact types

### `rule` — always-on guidance

Compiles into the `AGENTS.md` ambient block. Keep `rule.text` to ≤ 2 lines.

```yaml
artifact: rule
enforcement: advise
rule:
  text: |
    never(commit): secrets|keys|tokens; before(dependency): verify(exists_in_registry)
```

### `hook` — a declarative gate

The workhorse. Describe the trigger and message under `hook.gate` in `manifest.yaml`;
`chock compile` emits the shim and a self-contained Python runner.

```yaml
# manifest.yaml
artifact: hook
enforcement: block
effects: [read_only]
hook:
  gate:
    kind: content_regex
    "on": [commit]
    action: block
    message: >
      Remove console.log before committing.
    params:
      content_pattern: 'console\.log'
```

Rules for guard design:

- **Deterministic only** — no LLM calls, no network in the gate itself.
- **No hand-written scripts** — the compiler vendors the runner; maintain `hook.gate` in `manifest.yaml` only.
- Keep `message` actionable; the runner prints it to stderr on block.

### `skill` — an on-demand procedure

A `SKILL.md` (≤ 150 lines) plus `references/` for depth and optional `scripts/`. Skills are run by
*your* agent, not the CLI. `chock install-skills` installs them into your agent.

### `subagent` — a scoped worker

A `subagent.yaml` describing a delegated worker with its own input schema and effects.

## Declarative gate DSL

Chock compiles `hook.gate` in `manifest.yaml` into a `gate.json` and runs it with the
vendored `.chock/bin/gate.py` via a shim that probes `python3`/`python`/`py` for an
interpreter that can import `tomllib` (Python 3.11+) and exits 2 if none is found. The
`kind` picks the deterministic check:

- `content_regex` — scan added lines (or the whole staged blob) for a regex, and reject changes to files matching a path regex. Optional `allowlist_pragma` for lines that intentionally contain the pattern.
- `forbidden_ref` — block direct commits or pushes to protected branch refs.
- `dependency_allowlist` — allow only dependencies listed in an `allowlist_file` when adding to watched manifests.

```yaml
hook:
  gate:
    kind: content_regex
    "on": [commit, push]
    action: block
    message: >
      Staged changes contain forbidden content.
    params:
      content_pattern: 'TODO'
      forbidden_path_regex: '\.secret$'
      allowlist_pragma: '#\s*pragma:\s*allowlist\s+secret'
      scan: added_lines
```

## Effects & approval, in one rule

> A guard that *inspects and blocks* is `read_only` and never needs approval. Approval and the
> `irreversible` / `writes_external` effects describe the **action being governed**, not the guard.

## Validate as you go

```bash
chock check        # schema, budgets, security, eval minimums
chock compile <id>      # emit surfaces + coverage
```

Every policy needs evals before it's done — see [Evals](evals.md). For the fields the validator
enforces, see [Validation](validation.md).

## V3 manifest surface

### `hook.gate` replaces `gate.yaml`

A hook's gate lives under `hook.gate` in `manifest.yaml`. There is no separate `gate.yaml` file.
`chock compile` flattens `hook.gate` into `.chock/compiled/<id>/git-hook/gate.json`,
which the vendored runner enforces. See [Gate DSL](../spec/gate-dsl.md) for the full field reference.

### `rule.text` replaces `rule_text`

A rule's text lives under `rule.text` in `manifest.yaml`. The top-level `rule_text` key is gone;
`additionalProperties: false` rejects it. The compiled `AGENTS.md` block byte-matches `rule.text`
between the `<!-- chock:rules:start -->` markers (SEC-7).

### Skills and workflows carry no `manifest.yaml` (D1)

A skill's `SKILL.md` frontmatter **is** the manifest. The manifest is projected from
`metadata.chock.*` keys in the frontmatter:

```yaml
---
name: my-skill
description: >
  One-line description. args(request) returns(outcome) invoke(intent) exclude(anti-intent)
metadata:
  owner: team-platform
  version: "0.1.0"
  status: draft
  chock:
    id: my-skill
    skill_type: code
    effects: [read_only]
    provenance:
      author: team-platform
      trust_tier: community
    security:
      content_instructions: never-obey
    evaluation:
      test_suite_ref: evals/suite.yaml
---
```

Having both `manifest.yaml` and `SKILL.md` in the same directory is a hard error — the loader
raises `ManifestSourceError`. Composites use `manifest.yaml` (they have no `SKILL.md`).

### `interface.yaml` — optional sibling for I/O schema

For `code` and `hybrid` skills, `input_schema`, `output_schema`, and `evaluation` can be large.
Putting them in SKILL.md frontmatter would inflate the startup context cost for every agent that
loads the skill. Instead, an optional `interface.yaml` sibling file supplies them:

```yaml
# interface.yaml
input_schema:
  type: object
  properties:
    request: {type: string, description: "The request"}
  required: [request]
  additionalProperties: false
output_schema:
  type: object
  properties:
    outcome: {type: string, enum: [success, failure, needs_handoff]}
  required: [outcome]
  additionalProperties: false
evaluation:
  test_suite_ref: evals/suite.yaml
```

The loader merges `interface.yaml` lazily — only when the manifest is actually loaded, not on every
SKILL.md read. If the file is malformed, the loader warns and ignores it.

### `skill_type` conditionality

| `skill.skill_type` | Required fields |
| :--- | :--- |
| `nl` | `skill.skill_type`, `skill.entry`, `skill.effects` |
| `code` / `hybrid` | above + `input_schema`, `output_schema`, `evaluation`, `security`, `skill.approval` |

### Schema files

The manifest schema is split across eight files under `src/chock/validation/schemas/`.
The `validate` skill copies them into `.agents/skills/validate/assets/` when it is installed
so a consumer repo can read them locally.

| File | Contents |
| `manifest.schema.json` | Top-level properties, `oneOf` payload dispatch, `allOf` conditionals ref |
| `manifest.artifact-conditionals.json` | Per-artifact `if/then` requirements |
| `manifest.rule.json` | `rule` payload schema |
| `manifest.hook.json` | `hook` payload schema (gate) |
| `manifest.skill.json` | `skill` payload schema |
| `manifest.workflow.json` | `workflow` payload schema |
| `manifest.common.json` | Shared definitions (provenance, lifecycle, effects, security, etc.) |
| `manifest.provenance.json` | Provenance + lifecycle + validation definitions |

### Compliance report

`chock compliance report` lists the OWASP ASI controls and which installed policies claim
coverage. A policy's `compliance` field is a list of claim objects:

```yaml
compliance:
  owasp_asi:
    - control: ASI02
      coverage: partial
      note: blocks destructive commands
```

A bare-string claim in the list renders as `partial`. Per-claim `coverage` is `partial` or
`full`; the report's per-control states are `covered`, `partial`, `uncovered`. The report
is all `uncovered` until policies that claim controls are installed.

### Validated but not yet consumed

The following manifest fields are **declared and schema-checked** but **not yet consumed by the
compiler or runtime**. They are intentionally forward-declared so future handovers can activate them
without a schema migration. Filing bugs against them for "not doing anything" is incorrect — they
correctly do nothing today.

| Field | What it will do | Status |
| :--- | :--- | :--- |
| `applies_to` | Scope a policy to specific agents/model tiers | Schema-checked, not consumed |
| `propagation` | Control whether a policy inherits or is local-only | Defaulted to `inherit` for non-advise; not consumed |
| `concerns` | Tag a policy with cross-cutting concern labels | Schema-checked, not consumed |
| `conflicts_with` | Declare mutual exclusions between policies | Self-conflict checked; not consumed for routing |
| `bundle` | Group policies that ship together | Shared-asset escape checked; not consumed for packaging |
| `validation.last_validated` | Evidence a policy was validated: `date`, `chock`, `eval_score` (and optionally `model`) | Optional. If present, **all** of those fields are required — a partial attestation is a schema error. `chock check --only evals` (deterministic replay) can supply the `eval_score`; nothing writes the field automatically. |
| `dependencies.policies` | Declare policy-to-policy dependencies | Self-dependency checked; not consumed for ordering |
| `workflow` | Declare a deterministic workflow for workflows | Step `uses` checked against deps; not consumed for execution |
