# Script-Backed Gates

A declarative `hook.gate` answers one question about the diff: does a regex match, is this ref
protected, is this dependency allowed. Some checks cannot be written that way. A check that
compares **both revisions** of a file — what an element carried before against what it carries
now — gets no answer from knowing which side of the diff a line is on.

Such a policy ships its own script and declares the events that run it.

## The declaration

```yaml
# manifest.yaml
artifact: rule
enforcement: block
effects: [read_only]
rule:
  text: |
    never(erase): a name an element already had
hook:
  script:
    "on": [commit]        # commit | push, at least one
```

```
.agents/policies/<id>/
└── implementations/
    └── <id>-pre-commit.py      # or -pre-push, or .sh
```

`on` is **authoritative**. The compiler wires exactly the events it names — never what the
directory happens to contain — and `chock check` fails (**DET-5**) when a declared event has no
script, or a shipped script is not declared. Each mismatch fails differently and neither is
silent: the first would point a consumer's hook at a path that is not there, the second leaves a
policy enforcing less than its directory suggests.

## The contract

- **No arguments.** At pre-commit the guard already has both revisions: `git show :path` is the
  staged blob and `git show HEAD:path` its predecessor. Nothing is passed in.
- **The working directory is the repo root.**
- **The exit code is the verdict** — 0 allows, anything else refuses. A shim whose script has
  gone missing exits 2 rather than 0: a gate that cannot find its own guard must refuse.
- **Stdlib only**, like the vendored runner. The script is copied into every adopting repo, so
  it may not import anything that repo does not already have.
- **No `message`.** The script prints its own refusal, with detail no manifest string could
  hold — which file, which element, what it carried before.

## A rule may declare one

`artifact: hook` has no payload for rule text, and its ambient surface is a machine rendering of
the gate spec. A script-backed check has no spec to render, so forcing `artifact: hook` would
trade the hand-authored rule an agent reads for a near-empty stub. A `rule` may therefore carry
a `hook` holding only a `script`: the script is not a second artifact but the same control on a
second surface.

A **declarative gate** stays `artifact: hook`. A rule carrying one is an error, so no artifact
ever has two answers to what enforces it.

## Not a command guard

Two different files, two different contracts, and confusing them is silent:

| file | invoked by | gets | verdict |
| :--- | :--- | :--- | :--- |
| `implementations/<id>.sh` | in-agent PreToolUse hooks, the eval runner | a command's argv | exit code |
| `implementations/<id>-pre-commit.py` | the installed git hook | nothing | exit code |

The eval runner excludes the event-named scripts, because handing one an eval case's command
would score a verdict it never gave. A policy backed only by an event script therefore stays
tier 3 in `chock check --only evals` until the runner can stage a tree for it.

## See also

- [Authoring Policies](authoring-policies.md) — the other artifact types and their manifests
- [Enforcement Surfaces](enforcement-surfaces.md) — what `git-hook` means once wired
