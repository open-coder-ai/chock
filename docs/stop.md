# Stop: a person's stop on agents in one repository

```bash
chock stop   [--repo .] [--agent <client>] [--reason "<why>"]
chock resume [--repo .]
```

`stop` writes .chock/stop.json (scope, reason, who as git `user.email`, when). While it exists:

- every tool call an agent in scope makes is refused at Chock's pre-tool hook, reads included, with
  `stopped: <reason>`; the Devin hook too;
- an agent's commit or push is refused at the git hooks; a person's passes (the agent rule in
  [Decision log](decision-log.md#who-did-what));
- neither `CHOCK_ALLOW` nor the rollout level (`observe`, `ask`) loosens it;
- a file that exists but cannot be read or parsed refuses every agent (fail closed).

`--agent` names one client (`codex_cli`, `claude_code`, ...); without it every agent is stopped. At a
git hook the client comes from the agent's marker, lower-cased with `-` read as `_`: a client whose name
starts with the scope is reached (`cursor-agent` by `cursor`), so is a shorter form of it (`AI_AGENT=codex_...`
is `codex`, reached by `codex_cli`), and so is an agent naming no client or one no Chock client id matches.
All three err toward refusing.

A stop reaches every repository the call works in or touches: the session's project root as the client
names it, the one Chock's hook runs for, every repository above the call's folder and above each path
anywhere in its input or named by a word of its shell command (a nested repository inside a stopped one
included, symlinks resolved, `file://` URIs decoded), and, from a linked worktree (`git worktree add`, Claude Code's `.claude/worktrees/`), the
main checkout's stop as well as its own; for a bare repository's worktrees, the bare repository's. The
file is not committed, so a worktree has no copy of its own.

`stop` also writes `~/.chock/stops/<sha256 of the repository's realpath>.json` (`0o600`), and `resume`
removes it. A hook whose client names no project root for the session refuses every call of an agent in
scope while any entry on the machine is in force, whatever its folder: fail closed. A session the client
roots in an unstopped repository is not stopped by another repository's stop, unless the call names a path
in it: `rm <A>/.chock/stop.json` or `chock resume --repo <A>` from a session in B is refused. A registry
folder or entry that exists but cannot be read refuses. On macOS and Windows the entry is named by the
case-folded realpath, so a `resume` typed in another case clears it.

While no stop is in force in the call's own repositories and no registry entry reaches its agent, the hook
reads nothing of the call's input. Otherwise it reads at most 256 distinct strings, 64 KiB of them, for 2
seconds; a call past that cap is refused.

| Client | Project-root signal | Source |
| --- | --- | --- |
| claude_code | `CLAUDE_PROJECT_DIR` in the hook's environment | code: Chock's session-start hook reads it; live unmeasured |
| cursor | `workspace_roots` in the payload | measured live, Cursor 3.22.12 on Windows, 2026-10-06 |
| antigravity | `workspacePaths` in the payload | tests' payload fixtures; live unmeasured |
| openhands | `OPENHANDS_PROJECT_DIR` in the hook's environment | vendor docs as quoted in Chock's store data; live unmeasured |
| gemini_cli | `GEMINI_PROJECT_DIR`, read when set | unmeasured |
| every other client | none known: machine-wide | unmeasured |

At git hooks the stop is looked up as the dispatcher finds it: the work tree (`GIT_WORK_TREE` too), the
checkout of the git dir and of the common dir (`GIT_DIR` too), and every folder above each. Only the main
checkout's `.chock/bin/gate.py` judges, never a copy in the work tree. A bare repository has no main
checkout, so while its stop is in force every commit and push from its worktrees is refused, a person's
included, until `resume`.

Only a person changes a stop: `stop` and `resume` refuse, and log the refusal, when the shell carries any
agent marker. `resume` also needs a person at their own terminal: it refuses unless stdin and stdout are
both a TTY, and it asks for the repository's folder name to be typed before it removes the stop. `stop`
needs no terminal. `CHOCK_AGENT_COMMIT=0` clears no agent marker for any stop check (commit, push, stop,
resume): an agent can set it too. `resume` removes the file and the registry entry.

## Everywhere: one stop for the machine

```bash
chock stop   --everywhere [--reason "<why>"]
chock resume --everywhere
```

`stop --everywhere` writes `~/.chock/stops/_everywhere.json` (`0o600`, beside the per-repository entries; no
sha256 name starts with `_`). While it exists every Chock hook on the machine refuses every tool call, whatever
its repository, session or client: the sync hooks, every plugin's `--stop-check`, the gateway, and an agent's
commit or push at the git hooks. The refusal says the machine is stopped and that `chock resume --everywhere`
lifts it. `--agent` is refused with it: the scope is every agent. A file there that is not a regular file (a
folder, a symlink), or cannot be read or parsed, refuses too (fail closed).

At the git hooks only the main checkout's `.chock/bin/gate.py` tells an agent from a person, so the machine-wide
stop never refuses a commit blind: in a bare repository, a checkout without `gate.py`, or with no python on `PATH`,
it is left to the pre-tool hook, and a person's commit passes. A repository's own stop still refuses there.

`resume --everywhere` is person-only, as `resume` is: it refuses an agent's shell (logged), needs stdin and
stdout to be a TTY, and asks for the word `everywhere` to be typed. It removes that file only; a
per-repository stop stays in force, and its output says so. `chock status` and `chock doctor` lead with
`STOPPED EVERYWHERE` while it is in force. Run inside a repository, `stop` and `resume` write the same log
lines as the per-repository ones, with `"everywhere": true`; outside every repository they write none. Nothing
is sent over the network.

Unstopped, the hooks' fast path is unchanged: the registry folder they already list is the only look.

`chock sync` wires one hook of its own per client, `--stop-check`, with no matcher and whatever
policies are installed, so the stop sees every tool call, reads included. The plugin route carries
the same entry, in every client format (Devin's included):

| Route | Stop check |
| --- | --- |
| `chock sync` | one per client, beside chock's other entries |
| `chock install` bundle | one per bundle; member toggles never reach it |
| `chock plugin build` package (the marketplace route) | one per package that ships hooks |
| an advisory-only package (skill text, no hooks) | none, as `chock sync` wires none where it wires nothing |
| `chock gateway run` (MCP) | in the gateway, before its gates: every `tools/call` |

The gateway refuses each `tools/call` while a stop reaches it (an MCP error, `stopped: <reason>`); it
forwards `initialize`, `tools/list` and every other method, so the client can still connect and list
tools. It judges a stop in its `--repo`, its working directory, and every folder `initialize` names
(`roots`, `workspaceFolders`), each resolved to its repository (the nearest folder holding `.git`) as the pre-tool hook does. The client is
the MCP `clientInfo.name` read as a client id (`claude-code` is `claude_code`; `codex-mcp-client` is
`codex`, reached by a stop on `codex_cli`); a name that is no client's is reached by every stop.
`clientInfo.name` is the client's own claim. A stop file it cannot read, or a check that fails, refuses.

With several packages installed, each runs its own check on every tool call. Unstopped it allows and
logs nothing of its own beyond the call's one allow line. `chock status` shows a stop on its first line. Every refusal, the stop and
the resume are logged ([Decision log](decision-log.md#stop-and-override)). The file is local state:
`chock init` lists it in `.gitignore`, and CI never reads it.

**Limits.**

- It reaches only agents whose hooks Chock wires and that the client runs. An agent with no hook is
  stopped at commit and push only.
- Devin's hook is best-effort: the vendor runs it fail-open, so a hook that errors or times out lets
  the call through.
- It refuses the *next* action. It does not end a process already running (a background shell, a
  spawned server), and it revokes no credential.
- A person, or an agent working outside this repository's hooks, is not affected. Such an agent can also
  delete .chock/stop.json or `~/.chock/stops` directly: both are protected only from agents whose calls a
  hook judges. An agent with an unrestricted shell on a client without hooks is not stopped.
- A stop holds against agents in the stopped scope. An agent running unstopped elsewhere on the same machine, with a shell, can remove the stop (for example by deleting the files); the hook and protect-agent-config refuse the common forms, not every one. `stop --everywhere` leaves no hook-wired agent unstopped; an agent with no Chock hook is not reached by it.
- The terminal check is best-effort: an agent that can run a shell may give `resume` a pseudo-terminal
  (`script`, `expect`) and type the name. The hook refuses a call naming a stopped repository, and
  protect-agent-config refuses writes to any `.chock/` folder or `~/.chock/stops` (it does not refuse the
  `chock resume` command itself, measured against chock-catalog `ca0ddc9`), but
  an agent whose command hides the path (built at run time) is stopped only by those hooks' reach.
- The registry lives under the home folder. An agent whose hook runs with another `HOME`, or that deletes
  `~/.chock/stops` from a session no hook-judged stop reaches, skips the machine-wide registry: hooks that
  cannot place their session then see no stop, and a stop elsewhere is found only through the paths a call
  names.
- A plugin built before the registry existed does not read it: there the stop reaches only calls that
  touch the stopped repository.
