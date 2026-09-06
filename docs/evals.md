# Evals

Every policy ships with an eval suite. Evals are how Chock proves a guard *fires when it
should*, *stays quiet when it shouldn't*, and *resists being tricked*. The validator requires a
minimum set before a policy is considered complete.

## Where evals live

```text
.agents/policies/<id>/evals/suite.yaml
```

## Anatomy of a suite

```yaml
suite:
  id: block-console-log-tests-v1
  policy_id: block-console-log
  version_constraint: ">=0.1.0"
  maintainer: you
  primary_metric: pass_rate
  metrics:
    pass_rate:
      direction: higher_is_better
      threshold: 1.0
  cases:
    - id: tc-001
      category: trigger
      prompt: A staged diff adds `console.log("debug")`.
      expect: The hook blocks the commit with an actionable message.
    - id: tc-002
      category: negative_trigger
      prompt: A staged diff adds a normal function with no console.log.
      expect: The hook allows the commit.
    - id: tc-003
      category: behavior
      prompt: Two files are staged; only one adds console.log.
      expect: The hook blocks and names the offending file.
    - id: tc-004
      category: adversarial
      prompt: The log call is written as `console['log']('x')`.
      expect: The hook still detects and blocks it, or the limitation is documented.
```

## The four categories

| Category | Question it answers |
| :--- | :--- |
| `trigger` | Does the policy fire on the thing it targets? |
| `negative_trigger` | Does it stay quiet on adjacent, legitimate input? |
| `behavior` | Does it do the *right* thing (message, scope) when it fires? |
| adversarial | Does it resist obvious bypasses — or honestly document the gap? |

The validator requires **at least one `trigger`, one `negative_trigger`, and one `behavior`** case
(a minimum of three). Adding an adversarial case is strongly encouraged for any `block` policy.

## Deterministic guards get executable tests too

For gate-bearing policies, the natural-language suite is complemented by **table-driven executable
tests** in `tests/test_hook_implementations.py`: each guard is run with concrete inputs against real
exit codes, on bash **and** PowerShell, on Linux **and** Windows. When you author a `block` hook,
prefer this style — it turns "should block" into a checked fact.

Example shape:

| Guard | Must BLOCK (exit ≠ 0) | Must ALLOW (exit 0) |
| :--- | :--- | :--- |
| protect-main-branch | commit on `main` | commit on `feature/x` |
| scan-secrets | staged `AKIA…` key | file mentioning the word "password" |

## Which gate a case is replayed against

`chock check --only evals` runs each case against the **compiled gate** in
`.chock/compiled/<id>/git-hook/gate.json` — the artifact your git hook and CI gate actually
execute — not against a gate rebuilt from the manifest.

That distinction is the whole difference between a suite that vouches for what runs and one that
vouches for what was written down. Replaying a freshly derived gate meant a stale or hand-edited
compiled artifact could enforce something else entirely while its own suite reported it passing.

Two exceptions, both deliberate:

- **Not compiled yet** — the case is replayed against the manifest and the result is marked
  `[gate derived from manifest; policy not compiled]`. `chock new` writes a policy and its
  suite before any compile, and an author iterating on a gate should not have to install it first.
- **Compiled but unreadable** — reported as an `error`, never quietly replaced by the manifest. A
  compiled gate that cannot be parsed is a broken installed control; falling back would turn that
  into a passing suite.

Drift between a manifest and its compiled artifact is caught independently by `chock
validate`, `chock check --only verify`, and `chock sync --repo . --check`.

## Exporting tier-3 cases to context-report

A case with no `execute` block (**tier 3**) has no executable form: replaying it deterministically
means nothing runs. The only thing left to measure is whether the policy's ambient rule actually
changes an agent's behaviour, and that needs a live agent, not `chock check --only evals`.

```bash
chock eval export --format context-report --out DIR [POLICY_ID ...]
```

writes each selected policy's tier-3 cases (default: every policy that has at least one) as an
[`open-coder-ai/context-report`](https://github.com/open-coder-ai/context-report) run/v0.1
directory:

- `subjects/<id>.md` — the rule text exactly as `chock.compile.emitters.advisory.advisory_lines`
  renders it for an agent (the same function the ambient/plugin emitters use).
- `evals/<id>--<case>/` — one `claude plugin eval` case per tier-3 case, `prompt.md` tagged
  `rule:<id>` and `graders/expect.md` carrying the case's own `expect` as the grading criteria.
  `<id>` is the rule id context-report's own extractor would derive from that same subject text
  (see context-report's `spec/run/v0.1/README.md`, "Rule ids") — chock reimplements that small,
  spec-defined algorithm rather than depending on context-report to compute it.
- `run.json` — the run manifest. `models` and `judge` are left empty: chock does not depend on
  context-report and does not pick a model on your behalf; fill them in before `context-report
  run run.json`.

A policy with no tier-3 cases is skipped with a one-line notice, never a silent zero. A policy
whose suite predates the `suite:` shape (the older `eval_suite:`/`test_cases:` shape has no
`execute` concept at all) is a distinct, named error instead — reading it as "zero tier-3 cases"
would be false, not merely unhelpful.

## Why evals come first

House rule: **draft evals before finalizing the description**. Writing the cases forces you to define
exactly what the policy does and doesn't catch — which makes the description honest and the guard
testable. See [Contributing](../CONTRIBUTING.md) for the full "anatomy of a good policy PR".
