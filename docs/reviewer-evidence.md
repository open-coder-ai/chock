# Reviewer evidence

`chock review` records what a review of a change rests on, in a form the next reader can
re-derive rather than trust.

```bash
chock review emit --base origin/main --kind agent --by claude-code
chock review verify .chock/evidence/<sha>.json
```

`emit` writes the evidence file either way -- a record of failure is evidence too --
but exits non-zero when any check fails, so CI and scripts cannot mistake a
failing run for a clean one.

## Two kinds of claim, kept apart

This is the whole format:

| | Meaning | Worth |
| :--- | :--- | :--- |
| `verified` | a named check the verifier re-runs | what the re-run says |
| `attested` | a named reviewer's judgement | what the reviewer is worth |

A schema that let an attestation render like a verification would be the review-time version of
crediting an enforcement surface nothing installs — the failure the
[coverage taxonomy](enforcement-surfaces.md) exists to prevent. So `verify` never reports an
attestation as checked, and prints each one under **NOT verified** with its stated basis.

Its output is deliberately blunt when there are none:

```
  0 attestations. Every criterion needing judgement is unaddressed.
```

An automated run produces exactly that, and it should: a machine cannot attest.

## Three rules, each because the obvious version is unsafe

**The verifier never runs a command from the evidence.** `check` names an entry in the
repository's registry, and the verifier runs *that*. The `command` field is recorded for a human
reader, compared, and reported when it differs — never executed. Evidence is
contributor-authored; executing a string from it would hand arbitrary code to CI through the
artefact meant to increase trust.

**`unattestable` is recomputed from repo config**, not read from the file. Otherwise a submitter
shortens the list and self-certifies the machinery that checks contributions. Same rule
`verify` applies to the vendored runner: the thing being checked does not get to define the
check.

**`diff_sha` excludes `.chock/evidence/`.** Evidence is committed alongside the change,
so without the exclusion writing the file would change the diff the file attests to, and no
evidence could ever be valid.

## What expires it

`diff_sha` is a digest of `git diff <base>...HEAD`, so any content change invalidates it:

```
evidence is stale: it describes diff 2a1a6f5e2efd, the branch is now ada0aa823b3d.
```

A rebase that changes no content leaves it intact — deliberately. The binding is to *what the
change is*, not to which commit happens to carry it.

## `emit` refuses an empty diff

`diff_sha` is computed from **committed** state, so running `emit` before committing produces
evidence describing no change while the checks report on a working tree that has it:

```
[ERROR] nothing to attest: the diff against origin/main is empty (the working tree has
        uncommitted changes -- `diff_sha` is computed from committed state, so commit first).
```

It would fail safe either way — `verify` recomputes and reports stale once the work lands — but
silently and much later. The refusal names which of the two causes applies: uncommitted work, or
a branch identical to its base. `--allow-empty` records it anyway.

## The check registry

Built-ins, re-derivable in any adopter repo: `validate`, `eval`, `recompile-check`, `verify`.

A repository adds its own in `.chock/config.yaml`:

```yaml
chock:
  review:
    checks:
      effects-honesty: [python, tools/check_effects.py]
    unattestable_paths: [tools/, .github/workflows/]
```

Config is safe as a source here for the reason evidence is not: it is committed, and CODEOWNERS
routes it for review. An unknown `check` fails verification rather than being skipped — a claim
nobody can re-derive must not pass quietly.

## `chock review require` -- is this PR merge-ready?

`emit` and `verify` are available to anyone; `require` is the CI-side gate a maintainer wires as a
required status check. It re-derives the mechanism *Proof-or-Stop: Don't Trust the Agent, Trust the
Evidence* ([arXiv:2607.14890](https://arxiv.org/abs/2607.14890)) already publishes, for chock's own
threat model: an anonymous fork, with no signing keys, no producer authorization, and no
cooperation to rely on.

```bash
chock review require --base origin/main
```

Five judgements, in order, stopping at the first that fails:

| # | Judgement | Fails when |
| :--- | :--- | :--- |
| 1 | Present | no evidence file matches the head's `diff_sha` |
| 2 | Valid | `chock review verify` returns failures |
| 3 | Sufficient | the evidence's `command_set_hash` does not match this repository's `required_checks`, hashed from repo config right now |
| 4 | Passing | any required check is recorded `fail` |
| 5 | Attested | the diff touches an `unattestable` path with fewer than `attestation_floor` attestations |

Every failure names the exact `chock review emit` command to run next, or which line of the
evidence file to add an attestation to -- written for a contributor who has never heard of chock.

### `command_set_hash` -- the fix for self-certified checks

Nothing before this stopped a contributor from naming one trivial check and having it verify
cleanly: `verify` only re-derives what the file names. `emit` now records a `command_set_hash`
over the repository's `required_checks`, resolved to their actual registry commands; `require`
recomputes that hash from repo config -- never from the evidence -- and rejects any mismatch. A
lookup would only catch an omission; the hash also catches a shrunk set, a renamed check, or a
registry entry redefined after the evidence was produced, because any of those changes the hash
even when every named check is still present and passing.

### Config

```yaml
chock:
  review:
    required_checks: [validate, eval]   # the source; require hashes it and compares
    attestation_floor: 1                # attestations needed once the diff touches unattestable_paths
    applies_to: forks                   # all | forks | first_time -- for your own CI wiring
```

`required_checks` and `attestation_floor` both default to "off" (empty set, no floor) -- the same
judgement that is silent when nothing is declared stays silent, exactly like `unattestable_paths`.
`applies_to` is not enforced by `require` itself; it is there for your own workflow's `if:` condition
(§docs/adopting.md), because requiring evidence from everyone is friction that lands on volunteers.

### Wiring it as a required status check

`require` depends on `chock.review`, so it runs as a CLI subcommand in your own CI step -- **not**
a compiled git-hook or ci-gate. (`gate/runner.py` is vendored stdlib-only and must never import
`chock.review`; re-implementing `verify` there would fork the logic that exists specifically to be
un-forkable.) Add a step using this repository's `action.yml`:

```yaml
- uses: actions/checkout@v4
  with:
    fetch-depth: 0
- uses: open-coder-ai/chock@v0.1.0
  with:
    command: review require --base origin/main
```

Then mark that job a **required status check** in branch protection -- see
[Adopting Chock](adopting.md#the-branch-protection-gap) for why the workflow file alone is not
enough.

## What this does not do

- **It does not decide whether a change is good.** It records which claims were machine-checked
  and which were judgement, and makes the second kind legible.
- **It does not score reviewers.** Calibration — trust earned by how often attestations survive
  contact — needs real volume before it means anything.
- **It does not make review find more bugs.** Against the finding that 61% of organisations
  shipped a production incident from AI code that had already passed review and tests, this is
  silent by construction: it makes what review *rested on* checkable, not deeper.
- **It is not required**, unless you install `require-review-evidence` and wire `require` as a
  required status check (above). Nothing rejects a PR for lacking evidence by default.
