- **Per-policy on/off inside the agent (builder v2, 2.1b).** Every merged plugin `chock install --selection`
  builds now checks `.chock/guardrails.json` (repo scope, committed) or `~/.chock/guardrails.json` (user
  scope, where the repository has none) before each member judges, honouring it only while it matches the
  record `chock bundle` keeps (below):
  `{"version": 1, "bundles": {"<bundle.name>": {"<policy-id>": "on"|"off"}}}`, schema in
  `guardrails.schema.json`. An absent entry is on; on and off only. A file that is unreadable or invalid
  switches nothing off and prints a one-line warning. A member switched off answers the client's own
  allow and writes one line to `.chock/log/gate-events.jsonl` beside the governing file.
- **`chock bundle on|off <policy-id> [--bundle <name>] [--scope repo|user]` and `chock bundle status`** are the
  file's only writers and its reader. `status` lists every chock bundle installed in a client's default
  folder with each member's state and label. Every merged plugin also carries a "customize guardrails"
  skill that shows the members and prints the command for a person to run; it never writes the file.
- **Built-in self-protection, not switchable:** every merged plugin refuses an agent's write to either
  toggle file (shell guard, best effort, and an Edit/Write gate; case, `//`, `..`, backslashes and links
  folded) and an agent's own `chock bundle on|off` or `status --adopt`. Reads pass.
- **Turn-end check of the toggle files:** `chock bundle on|off` records each file's sha256 in
  `.chock/state/guardrails.sha256` beside it. Every merged plugin's Stop hook refuses a turn's end, in the
  client's own words and with the usual re-entry cap, while a toggle file in scope (repo or user) differs from
  that record: changed, deleted, or never recorded. That catches a write the best-effort shell guard missed,
  including on Copilot and Devin, which judge no write tool. The hook-time lookup honours a toggle file only
  while it matches that record; otherwise every guardrail stays on, with a one-line warning, so a file an agent
  wrote by any trick switches nothing off.
- **`chock sync` records a committed `.chock/guardrails.json` only when it is byte-identical to the remote
  default branch** (`origin/HEAD`, else `origin/main`), so a teammate's fresh clone honours the reviewed file
  once synced, and prints its on/off summary. A local commit that is not on the remote is never recorded: a
  person reviews it and runs `chock bundle status --adopt`, which the built-in guard refuses from an agent.
- **`chock check --only baseline` reports a member switched off in `.chock/guardrails.json` against the
  base branch, or the committed file deleted, as a loosening.**
