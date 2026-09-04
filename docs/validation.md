# Validation

`chock check [--repo PATH]` is the deterministic gate that keeps every artifact conformant. It's
the same check that runs in CI and as a pre-commit hook. Exit code is non-zero when there are errors.

```bash
chock check
chock check --only validate --mode frontier-claude
```

## What it checks

The engine runs a suite of independent checks (see `src/chock/validation/`):

| Check | Enforces |
| :--- | :--- |
| **Schema** | Each manifest matches its JSON schema (`rule`, `hook`, `skill`, `workflow`, `eval`). |
| **Content & budgets** | `SKILL.md` ≤ 150 lines · description ≤ 500 chars · reference files ≤ 300 lines · ambient rules ≤ 2 lines. |
| **Security** | No secrets, no `eval`/`exec`, no network in deterministic scripts; content-instruction safety. |
| **Evals** | Minimum coverage: at least one `trigger`, one `negative_trigger`, one `behavior` case. |
| **Determinism** | Operations that can be scripted are scripted (DET rules). |
| **Drift** | Frontier standards carry `fetched_at`; warns when a source is stale (> 90 days). |
| **Orchestration** | Multi-step/workflow manifests declare valid inputs, effects, and approval. |
| **Manifest ID** | `manifest.id` must match the folder name. |
| **Payload match** | Exactly one payload block (`rule`, `hook`, `skill`, `workflow`) must match the declared `artifact`. |
| **Block needs gate** | `enforcement: block|verify` requires a `hook.gate` definition. |
| **Gate params** | `hook.gate.kind` must be known; `params` must conform to the kind's param schema. |
| **Self-dependency** | A policy must not list itself in `dependencies.policies`. |
| **Self-conflict** | A policy must not list itself in `conflicts_with`. |
| **Bundle assets** | `bundle.shared_assets` must resolve within the policy directory. |
| **Workflow uses** | `workflow.steps[].uses` must reference a declared `dependencies.policies` entry. |
| **Repo standards** | No reviewable file exceeds 300 lines (`tests/test_repo_standards.py`). |

### Schema identifiers

The schemas live in `src/chock/validation/schemas/` and are identified under
`https://open-coder-ai.github.io/chock/schemas/v0/<filename>`, where they are also
published.

Validation never fetches them. `validation.loading` builds a store keyed by each document's own
`$id` and resolves `$ref`s offline, so `validate` works with no network — the published copy is a
convenience for readers and schema-aware editors, never a dependency.

They previously carried `$id`s under a domain the project does not own. Nothing was broken, since
an `$id` is an identifier rather than necessarily a URL. But an identifier that 404s is a worse
answer than one that serves the document, and an `$id` under a third party's domain could one day
resolve to content we do not control — a poor failure mode in a governance tool. `$id`s get pinned
by consumers, so the base is fixed by `tests/test_schema_identity.py` rather than left to a
find-and-replace.

## Severity levels

- **error** — must be fixed; fails the command and CI.
- **warning** — should be addressed (e.g. an unaddressed reference file, a stale frontier source).
- **info** — advisory.

The reference repo aims for a clean bill under its own tooling: findings on the reference repo teach
consumers that findings are ignorable.

## Frontier modes

`--mode frontier-claude` / `frontier-devin` layer on a frontier profile's extra expectations, so you
can validate a repo the way a specific agent ecosystem would.

## The five-place rule

Validation is one of five places every requirement must land, or it drifts:

```text
spec invariant → schema field → validator/runtime check → generation template → CI
```

`chock check --only matrix` verifies the spec ↔ enforcement-matrix half of that chain: every spec
invariant ID is listed, and every row has a non-empty `Check` column. `chock check --only mechanisms`
verifies the other half, enforcement-matrix ↔ code: a row naming a `` `function()` `` mechanism must
name one that actually exists in `src/`, is invoked on the `engine` or `lifecycle` dispatch path (both
are searched — checking only one produced this project's own false positives, see
`spec/enforcement-matrix.md`'s "How to read this matrix"), and can emit the severity the row claims. A
row that cannot be made true this way is not weakened to pass — it is marked `unautomated` (or `eval`,
when the eval suite enforces it instead) and the check skips it knowingly, not silently. When you add a
new check, add its spec invariant, schema field, generation-template support, and a CI step in the
same PR — plus one test that attacks the check and one that feeds it ordinary data.

## Running it in CI

The reference `.github/workflows/ci.yml` runs, on Ubuntu **and** Windows across Python 3.11/3.12:

```bash
ruff check . && ruff format --check .
chock check --only matrix
chock check --only mechanisms
chock check
chock check --only validate --mode frontier-claude
chock check --only validate --mode frontier-devin
chock registry scan     # then diff to detect a stale registry
pytest -q
```

See [Registry & Lockfile](registry-and-lockfile.md) for the registry-freshness check.
