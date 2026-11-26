# Doctor

Most clients fail open when a hook crashes, times out or never loads, so a silent hook looks
exactly like a protected session. `chock doctor` checks that each client's chock hooks are in
place, current, and seen running.

```bash
chock doctor [--repo .] [--client <id>] [--client-version <v>] [--sessions 3] [--json] [--live]
```

Read-only; no network, and it never runs a client (`--live` runs chock's own hook commands, below). For each client with chock hooks, on the
sync route (the vendored runtimes `chock sync` put in `--repo`) and the plugin route (bundles
`chock install` built into a client's default folder), it prints one line per check, `PASS`,
`WARN`, `FAIL` or `INFO`, with a one-line fix:

- **hooks**: the file the client reads runs chock's runtime, and the runtime is there;
- **launcher**: the launcher is there, and a `python3`, `python` or `py` on PATH is 3.11+;
- **engine**: the runtime is byte-identical to what the installed chock builds; a plugin's
  recorded engine (version and commit, in `chock.selection.json`) is compared too;
- **trust**: for clients that run a hook only once a person trusts it (Codex, Grok), how to;
  chock cannot read that record;
- **client**: the versions agentseam witnessed; `--client-version` compares yours;
- **last fired** and **heartbeat**: from the [decision log](decision-log.md), the last record per
  hook surface, and the `session_start` heartbeats. Tool-use records with no heartbeat warn; at
  level `debug`, no hook record in the last `--sessions` sessions warns. A client with no
  documented session-start event reads "no heartbeat available", never a failure.

`--client` takes an install client id (`claude-code`) or an agent id (`claude_code`). Exit 1
when any check fails or no chock hooks are found, else 0.

## `--live`: do the hooks refuse?

`--live` runs chock's own installed hook commands, as the client's config file writes them and from
the repo, and checks each answers as its client reads it. It starts no client, sends nothing anywhere
and logs nothing (the probe's session is removed afterwards). A command runs only if it is
byte-equal to what this engine renders for that client, and only when the launcher and every
vendored runtime are byte-equal to this engine's; any other hook command is counted, never run.
The installed policies' guard code runs, as it does in `chock check` evals.

- **live: refuses the canary**: the first installed pre-tool policy's own first refusing eval case
  must be refused by that policy;
- **live: allows a harmless command**: `echo chock-doctor-live` must be allowed;
- **live: refuses the canary prompt** and **live: allows a harmless prompt**: for a target with a
  `prompt_submit` gate installed, a policy's first `prompt_submit` eval case that must block must
  be refused by that policy's hook, and `hello` must be allowed. Only clients with a payload agentseam
  recorded for that event are probed; any other gets an `INFO` row.

A plugin target's hook commands are never run: its hook file can be re-rendered only from the
catalog it was built from, which doctor does not fetch. Its live row is `INFO`.

### `armed`

Every target ends with one row, `armed`, and `--json` carries it as `"armed": "yes" | "no" | "unknown"`.

- `yes`: hooks, launcher and engine are `PASS`, the live rows (the prompt rows too, where chock wrote a
  prompt-submit hook) are `PASS`, and the heartbeat is `PASS`;
- `no`: any row is `FAIL`; the row names the first one and its fix;
- `unknown`: anything else, and the row says which row left it so (a skipped live run, a heartbeat
  that is `WARN` or `INFO`, `--live` not given).

The heartbeat proves the client calls the hook; live proves the hook refuses. Only both together
are `yes`, so a fresh install reads `unknown` until a session has started. The exit code is unchanged:
1 on any `FAIL`.
