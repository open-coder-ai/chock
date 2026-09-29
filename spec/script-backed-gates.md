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
message file. It exits 0 to allow, anything else to refuse.
The pre-commit and pre-push scripts still take none.

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
`rule` may therefore carry a `hook` holding a `script`, a `gate`, or both -- neither is a second
artifact but the same control on more surfaces. A hook with both keeps its event script (say
`pre-commit`) and adds a gate at `tool_use`: the compiler emits the script's git shims and the
gate's surfaces, DET-5 still binds the script, and coverage is credited per surface (the script
backs the git event only). One git event has one shim, so a gate and a script may not both run at
`commit` or both at `push` (`manifest_script_events`); a gate may add `tool_use`, which a script
cannot.

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
never gave. The guard is resolved strictly as `implementations/<id>.{sh,py}` (else the legacy
map); no other file in the directory is ever taken for it.

## Eval cases for event scripts

An `execute` case with `event: pre-commit | pre-push | commit-msg` runs the policy's script for
that event in a staged throwaway repo: `head_files` committed, `files` staged, then the script
runs at the repo root as the shim would. `commit-msg` takes `message` (the text of the message
file passed as `argv[1]`); `pre-push` takes `stdin`, the lines git feeds the hook. Exit 0 is
`allow`, a refusal is `block`, a crash (exit 1 with no reason) is an error, so a broken script
never scores a block. Such cases are executable, not tier 3.

```yaml
execute: {event: commit-msg, message: "WIP\n", expect: block}
```

Gate cases may likewise run at the agent events: `event: tool_use | stop` with `writes` (the
files as the agent leaves them, not staged) and optional `head_files` and `added`, replayed
through the gate runner at that event.

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
