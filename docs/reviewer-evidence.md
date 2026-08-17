# Reviewer evidence

`chock review` records what a review of a change rests on, in a form the next reader can
re-derive rather than trust.

```bash
chock review emit --base origin/main --kind agent --by claude-code
chock review verify .chock/evidence/<sha>.json
```

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

## What this does not do

- **It does not decide whether a change is good.** It records which claims were machine-checked
  and which were judgement, and makes the second kind legible.
- **It does not score reviewers.** Calibration — trust earned by how often attestations survive
  contact — needs real volume before it means anything.
- **It is not required.** Nothing rejects a PR for lacking evidence today.
