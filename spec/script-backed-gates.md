# Script-backed gates

A check no gate `kind` can express — one needing **both revisions** of a file, where which
side of the diff a line sits on answers nothing — is declared as `hook.script` rather than
`hook.gate`, and run by the installed git hook.

```yaml
hook:
  script:
    "on": [commit]       # commit | push, >=1
```

```
.agents/policies/<id>/implementations/<id>-pre-commit.{sh,py}     # or -pre-push
```

No `kind`, no `params`, no `message`: the behaviour is the script's, and it prints its own
refusal with detail no manifest string could hold. The contract is empty on purpose — no
arguments, cwd at the repo root, exit code is the verdict, stdlib only — because at
pre-commit the script already has both revisions (`git show :path` and `git show HEAD:path`).

`on` is authoritative. The compiler wires exactly the events it names, never what the
directory happens to contain.

**DET-5**: a declared event MUST have a script on disk, and a shipped git-event script MUST
be declared. Either way round is an error, and each fails differently: one would point a
consumer's hook at a file that is not there, the other leaves a policy enforcing less than
its directory suggests.

## Which artifact may declare it

Either a `hook` or a `rule`. `artifact: hook` has no payload for rule text and its ambient
surface is a machine rendering of the gate spec; a script-backed check has no spec to render,
so requiring `artifact: hook` would trade the rule an agent reads for a near-empty stub. A
`rule` may therefore carry a `hook` holding only a `script` — the script is not a second
artifact but the same control on a second surface.

A declarative `hook.gate` stays `artifact: hook`. A rule carrying one is an error
(`manifest_payload`), so no artifact has two answers to what enforces it.

## Not a command guard

`implementations/<id>.sh` is invoked with a command's argv by the in-agent PreToolUse hooks
and the eval runner. An event script is invoked with nothing. The eval runner excludes the
event-named scripts, because handing one an eval case's command would score a verdict it
never gave; a policy backed only by an event script stays tier 3 in `chock check --only
evals` until the runner can stage a tree for it.

Prose, examples and the authoring path: `docs/script-backed-gates.md`.
