# Script-backed gates

A check no gate `kind` can express — one needing **both revisions** of a file, where which
side of the diff a line sits on answers nothing — is declared as `hook.script` rather than
`hook.gate`, and run by the installed git hook.

```yaml
hook:
  script:
    "on": [commit]       # commit | push | commit-msg, >=1
```

```
.agents/policies/<id>/implementations/<id>-pre-commit.{sh,py}     # or -pre-push, -commit-msg
```

No `kind`, no `params`, no `message`: the behaviour is the script's, and it prints its own
refusal with detail no manifest string could hold. The contract is empty on purpose — no
arguments (but commit-msg's, below), cwd at the repo root, exit code is the verdict, stdlib only — because at
pre-commit the script already has both revisions (`git show :path` and `git show HEAD:path`).

`commit-msg` is the one event with an argument: git's contract, `argv[1]` is the path of the
message file.
The pre-commit and pre-push scripts still take none.

**Exit codes**, at every event: `0` allows; `4` warns (the script's own words on stderr are the
warning, the hook exits 0); `3` asks (a hook cannot prompt, so it refuses unless a person set
`CHOCK_ALLOW=<policy-id>[,<policy-id>...]` for that command and the command is not an agent's, see
`spec/gate-dsl.md` "Agent commits"); anything else refuses, `1` with the script's reason and any
other code or a missing script as a broken install. The generated shim runs the script and hands a
`3` or `4` to `gate.py script-verdict`, which is why a script-only policy also vendors the runner.
A warn or an ask is a record in the gate log (`verdict: warn|ask`). A script-backed hook has no
declared action, so it is graded as enforcing; only a `hook.gate` with `action: warn` is not.

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
`rule` may therefore carry a `hook` holding a `script` or a `gate` -- neither is a second
artifact but the same control on a second surface. The hook still holds exactly one of the
two (`hook.gate` and `hook.script` together are a schema error).

A rule carrying a `hook.gate` keeps its own text as the ambient surface; the gate compiles to
the git-hook, pre-tool-use, stop and ci surfaces exactly as an `artifact: hook` gate does, and
the INDEX lists it as a rule. Any other payload beside `rule` is still a `manifest_payload`
error.

A policy may also ship a command guard, `implementations/<id>.{sh,py}`, beside a `hook.gate`
whose `"on"` includes `tool_use`. Both compile: the guard judges shell commands and the gate
judges the content a write leaves. Every vendor installer merges both entries, and the policy
reads as installed only when all of its compiled entries are present.

## Not a command guard

`implementations/<id>.sh` is invoked with a command's argv by the in-agent PreToolUse hooks
and the eval runner. An event script is invoked with nothing. The eval runner excludes the
event-named scripts (`-pre-commit`, `-pre-push`, `-commit-msg`), because handing one an eval case's command would score a verdict it
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
- **Exit codes.** `0` allows. `3` asks; the first output line is the prompt. (`4` warns only for a
  `script` gate and a script-backed git hook, above; a command guard exiting 4 is not checked.) `1` blocks only
  when the guard gave a reason: non-empty stderr (stdout also read) that is not a crash
  signature (`Traceback (most recent call last)`, `syntax error`, `SyntaxError`, `unexpected
  EOF`). Exit `1` with empty output or a crash signature is an interpreter failure and asks
  like any other non-zero exit. Existing guards that print a reason and `exit 1` are unchanged.
  A guard that means to block prints why.

Prose, examples and the authoring path: `docs/script-backed-gates.md`.
