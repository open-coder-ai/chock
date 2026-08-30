# Enforcement Surfaces

A **surface** is *where* a compiled control runs. The same policy is emitted to the strongest surface
each agent supports — that's how "author once, enforce everywhere" stays honest about *how* strongly
each guarantee holds.

## The eight surfaces

| Surface | Determinism | Bypassable? | What it is |
| :--- | :--- | :--- | :--- |
| `git-hook` | Hard, at commit/push | Yes (`--no-verify`) | Pre-commit / pre-merge-commit / pre-push guard |
| `ci-gate` | Hard, un-bypassable | No | The backstop for a skipped git hook |
| `ambient-rule` | Advisory | Yes | Compiled `AGENTS.md` block the agent is asked to follow |
| `pre-tool-use` | Hard, pre-execution | No | Blocks a command **before** the agent runs it, in each client's own deny dialect — Claude Code + Cursor (see the Cursor caveat) |
| `agent-hooks` | Hard, pre-execution | No | The same exit-2 deny for Copilot CLI + VS Code agent mode, from `.github/hooks/chock.json` (witnessed blocking on both, 2026-08-23) |
| `managed-setting` | Hard, org-level | No | Admin-deployed allow/ask/deny rules |
| `gateway` | Hard, un-circumventable | No | Budget/egress backstop — *modeled now, emitted later* |
| `mcp-gateway` | Hard, **MCP-routed tools only** | Yes (P3c) | A stdio proxy the client launches instead of the real MCP server; refuses matching `tools/call` payloads. Emitted today; **credits no agent** until the per-client config witness ships |

> **`agent-hooks` shell caveat, stated rather than glossed.** The surface genuinely
> enforces: it runs the guard before the tool call and honours exit 2 as deny (witnessed on
> both clients). On Windows, Copilot and VS Code run **PowerShell**, and before
> `block-destructive-commands` 0.0.6 the shipped guards were *bash-oriented* — they caught
> bash-syntax commands but not PowerShell-native destructive syntax. 0.0.6 closes that gap
> with a PowerShell/cmd guard matched against the raw command (`CHOCK_RAW_COMMAND`); other
> guards remain pattern filters, so the "non-standard shell" bypass class they document
> still applies to them. The hook's
> interpreter is resolved at run time (skipping the Windows Store `python3` alias stub) and
> the repo root via `git rev-parse`, so the committed file is portable with no baked path.

**`git-hook` + `ci-gate` are the universal hard floor** every agent shares. `pre-tool-use` and
`agent-hooks` are the premium tier available on agents that expose native controls — Claude
Code and Cursor via `pre-tool-use`, Copilot CLI and VS Code via `agent-hooks`.
`gateway` is reserved for cost/egress controls on the roadmap. `mcp-gateway`
([#32](https://github.com/open-coder-ai/chock/issues/32)) governs exactly the MCP slice:
tool calls routed through the proxy. An agent's native shell and file tools never cross
it, so shell-guard policies do not rise here -- content scanning on MCP writes and the
`egress_allowlist` gate kind do. Fail posture: fail-closed on the paths that matter --
a dead proxy means MCP calls error; an unreadable gate, an unknown kind, an empty
allowlist or a stripped pattern all refuse; a non-object `tools/call` params or a batched
request is screened, not skipped. The one gap the proxy cannot self-detect is being
pointed at the wrong repo, so `gateway run` **refuses to start** when `.chock/compiled`
is absent and prints the loaded-gate count to stderr on startup. One downstream server
per gateway process; wrap N servers with N entries.

> **What the gateway asks you to trust, stated plainly.** The proxy is a defensive
> interceptor — a well-established pattern (Docker, GitHub, and others ship equivalents),
> not a novel or secret technique. Three things bound what it can promise, and you should
> know each before relying on it:
>
> - **It is only as trustworthy as write-access to `.chock/compiled`.** Whoever can write
>   the gate files controls what the gateway allows or denies. Treat that directory as
>   security-sensitive — the `protect-agent-config` policy guards exactly these paths, and
>   the gateway is a reason to keep it enabled.
> - **It runs with your privileges.** The client launches it as a subprocess under your
>   account; it can do anything you can. That is why Chock releases are signed and
>   attested (Sigstore) and why the install verification is pinned — a tampered Chock
>   package is the realistic threat to a tool like this, far more than the published code
>   being "misused." Verify what you install.
> - **It governs MCP-routed tool calls only, best-effort.** Native shell and file tools
>   never cross it; host detection is regex over free-form arguments with documented gaps
>   (see `spec/gate-dsl.md`). It is friction on an MCP fetch/egress tool, not an airtight
>   boundary — pair it with a network-level control where the threat model demands one.

> **Cursor caveat, stated rather than glossed:** Cursor documents exit 2 as deny, but a
> hook returning exit 2 alone was **witnessed NOT blocking** on a real install
> (2026-08-24). The vendored adapter therefore also emits Cursor's stdout
> `{"permission": "deny"}` response, which is what actually blocks (witnessed). Cursor
> **fails open** on any other non-zero exit unless the hook entry sets `failClosed` —
> and `failClosed: true` would brick
> every shell command on a clone whose baked interpreter path does not resolve yet. Chock
> ships fail-open entries and mitigates the gap the same way as Claude's exit-127 case:
> install bakes an interpreter that provably runs. The guard covers shell commands
> (`beforeShellExecution`); other tool classes are not intercepted.

> **`managed-setting` is compiled but not installed.** The compiler writes
> `.chock/compiled/<id>/managed-setting/managed-settings.json` and nothing reads it — there is
> no installer, so it enforces nothing today. It is excluded from `INSTALLED_SURFACES` in
> `surfaces.py`, so no policy can raise a coverage claim through it. Read the row below as *what the
> agent could support*, not as something switched on.

> **`ci-gate` needs `chock sync --ci` to actually run.** The compiler always writes
> `.chock/compiled/<id>/ci-gate/gate.json` and `step.yaml`, but nothing invokes them until
> `install-ci` writes `.github/workflows/chock.yml`. The coverage report checks for that file
> before crediting `ci-gate` toward `enforced-at-commit` — the same check `pre-tool-use` gets, and for
> the same reason: unlike git hooks, nothing installs the CI workflow automatically as a side effect
> of `compile` or `recompile`.

## Per-agent coverage matrix

Which surfaces each agent supports today (from `src/chock/compile/surfaces.py`):

| Agent | ambient | git-hook | ci-gate | pre-tool-use | managed-setting | agent-hooks |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **Claude Code** | ✅ | ✅ | ✅ | ✅ | ✅ | — |
| **Cursor** | ✅ | ✅ | ✅ | ✅ | — | — |
| Copilot | ✅ | ✅ | ✅ | — | — | ✅ |
| Codex | ✅ | ✅ | ✅ | — | — | — |
| Gemini | ✅ | ✅ | ✅ | — | — | — |
| Windsurf | ✅ | ✅ | ✅ | — | — | — |
| Devin | ✅ | ✅ | ✅ | — | — | — |
| Aider | ✅ | ✅ | ✅ | — | — | — |
| Grok | ✅ | ✅ | ✅ | — | — | — |
| Kimi Code | ✅ | ✅ | ✅ | — | — | — |
| Replit | ✅ | ✅ | ✅ | — | — | — |
| Tabnine | ✅ | ✅ | ✅ | — | — | — |
| VS Code | ✅ | ✅ | ✅ | — | — | ✅ |
| Antigravity CLI | ✅ | ✅ | ✅ | — | — | — |

Claude Code and Cursor get `pre-tool-use`, Copilot CLI and VS Code get `agent-hooks`;
the rest get the shared hard floor plus advisory rules until their own native controls
are wired in.

## Coverage levels

For each policy × agent, the compiler records one of seven levels in `.chock/coverage.json`.
The first three come from agentseam's own honest, per-agent vocabulary
(`agentseam.matrix.enforcement_level`, owner decision #9) for an installed, in-agent
pre-execution control — chock no longer flattens every one of them to `enforced`, because
they are not the same claim: a hook that fails OPEN on a crash is a materially weaker
promise than one that fails closed, and an adopter deciding whether to trust a control
needs to see the difference.

| Level | Meaning |
| :--- | :--- |
| **`enforced`** | An installed, hard, pre-execution in-agent control that fails CLOSED — a crashed hook still blocks. |
| **`enforceable`** | Installed and blocks, and CAN be told to fail closed, but does not by default — what an adopter may claim depends on how the hook was installed. |
| **`best-effort`** | Installed and blocks, but fails OPEN — a crashed hook silently allows. claude_code's PreToolUse is this tier today. |
| **`enforced-at-commit`** | The policy emitted a git-hook (installed automatically) or a CI gate whose workflow `install-ci` has actually written — hard at commit time or over the PR's commit range, advisory in-agent. Chock's own commit-time mechanism, outside agentseam's per-agent-hook model. |
| **`advisory`** | Only the ambient rule applies — compiled prose the agent is asked to follow. Also outside agentseam's model: an ambient rule is not a lifecycle hook of any kind. |
| **`none`** | Nothing the policy emitted reaches this agent. |
| **`disabled`** | The policy is listed in `policies.disabled` and produces no artifacts or hooks. |

> **`enforced` is raised by the install step, not by `compile`.** Compiling writes a
> fragment; installing merges it into `.claude/settings.json` / `.cursor/hooks.json` and
> vendors the adapter that feeds the agent's JSON payload to the guard. Every `chock sync`
> runs that install step (`install-hooks` is its alias), so the documented adopter flow
> wires the guards it compiles. The claim is made by the step that performs the wiring, so
> it cannot get ahead of the mechanism. `ci-gate`'s contribution to `enforced-at-commit`
> follows the identical rule with `install-ci` in place of the hook installers.

> **The SessionStart arm hook is wiring, not a surface.** `chock sync` also installs a
> `SessionStart` entry (running the vendored `.chock/bin/claude_code.py`) into
> `.claude/settings.json`. It carries no coverage claim: its only job is re-installing the
> git hooks on a fresh clone — git never clones them — or printing the `chock sync`
> command into the session context when it cannot. See
> [Arming a fresh clone](adopting.md#arming-a-fresh-clone).

Example for `protect-main-branch` (targets git-hook + CI + PreToolUse + managed-setting):

```json
{
  "protect-main-branch": {
    "claude":  "best-effort",
    "cursor":  "enforced-at-commit",
    "copilot": "enforced-at-commit",
    "aider":   "enforced-at-commit"
  }
}
```

## How a policy picks its surfaces

A hook that must stop a command targets `git-hook` + `ci-gate` (the universal floor) and, where
available, `pre-tool-use` + `managed-setting`. A hook whose `on:` includes `tool_use` is compiled to
the `pre-tool-use` surface on agents that support it (Claude Code and Cursor; Copilot
CLI and VS Code get the same guard via `agent-hooks`). A best-practice rule with
no deterministic check compiles only to `ambient-rule`. The compiler always pairs a control with the
**strongest available backstop** — e.g. a git hook plus a CI gate, because a git hook alone can be
skipped with `--no-verify`.

## Gate runner semantics

At commit time the vendored runner scans the staged files git reports as added, copied,
modified, renamed, or type-changed. It disables `core.quotePath` for its diff calls, so
non-ASCII paths arrive unescaped and are scanned like any other file. `dependency_allowlist`
gates match their watched manifest basenames (e.g. `package.json`) anywhere in the tree, not
only at the repo root. In CI range mode, a base ref that cannot be resolved fails **closed** —
the gate exits 2 rather than passing an unscanned range.

## Reading the coverage report

`chock compile <id>` (and `init`) write `.chock/coverage.json`. Treat it as the source
of truth for "where does this guarantee actually hold?" — it's the foundation for the compliance
attestation on the [roadmap](../README.md#-roadmap).
