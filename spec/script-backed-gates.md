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

## Command guard contract

`implementations/<id>.sh|.py` runs under the in-agent hooks (`gate/guard_runner.py`) and the
eval runner, always, whether or not the command parses.

- **argv.** `shlex.split` (POSIX) when it succeeds -- unchanged. When it raises (trailing
  backslash, unbalanced quote, PowerShell quoting), argv is `command.split()` on whitespace and
  `CHOCK_ARGV_FALLBACK=1` is set. Not `shlex(posix=False)`: it raises on the same inputs. The
  fallback keeps quotes and backslashes in tokens (`C:\x` stays `C:\x`), so a guard that must
  see quoting reads `CHOCK_RAW_COMMAND`, the exact string, set on every run.
- **`CHOCK_TOOL`.** The tool that ran the command, from the hook payload's tool name:
  `bash` (Bash), `powershell` (PowerShell, pwsh), `shell` (sh, shell, run_shell_command,
  Cursor's beforeShellExecution, any other name containing "shell"), else `unknown`.
- **Exit codes.** `0` allows. `3` asks; the first output line is the prompt. `1` blocks only
  when the guard gave a reason: non-empty stderr (stdout also read) that is not a crash
  signature (`Traceback (most recent call last)`, `syntax error`, `SyntaxError`, `unexpected
  EOF`). Exit `1` with empty output or a crash signature is an interpreter failure and asks
  like any other non-zero exit. Existing guards that print a reason and `exit 1` are unchanged.
  A guard that means to block prints why.

Prose, examples and the authoring path: `docs/script-backed-gates.md`.
