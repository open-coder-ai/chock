# Enforcement Surfaces

A **surface** is *where* a compiled control runs. The same policy is emitted to the strongest surface
each agent supports — that's how "author once, enforce everywhere" stays honest about *how* strongly
each guarantee holds.

## The six surfaces

| Surface | Determinism | Bypassable? | What it is |
| :--- | :--- | :--- | :--- |
| `git-hook` | Hard, at commit/push | Yes (`--no-verify`) | Pre-commit / pre-merge-commit / pre-push guard |
| `ci-gate` | Hard, un-bypassable | No | The backstop for a skipped git hook |
| `ambient-rule` | Advisory | Yes | Compiled `AGENTS.md` block the agent is asked to follow |
| `pre-tool-use` | Hard, pre-execution | No | Blocks a command **before** the agent runs it (exit 2 = deny) |
| `managed-setting` | Hard, org-level | No | Admin-deployed allow/ask/deny rules |
| `gateway` | Hard, un-circumventable | No | Budget/egress backstop — *modeled now, emitted later* |

**`git-hook` + `ci-gate` are the universal hard floor** every agent shares. `pre-tool-use` is the
premium tier available on agents that expose native controls — Claude Code and Cursor today.
`gateway` is reserved for cost/egress controls on the roadmap.

> **Cursor caveat, stated rather than glossed:** Cursor's Agent Hooks honour exit 2 as deny
> (the same protocol as Claude's PreToolUse, spoken by the same vendored adapter through
> `.cursor/hooks.json` `beforeShellExecution`), but Cursor **fails open** on any other
> non-zero exit unless the hook entry sets `failClosed` — and `failClosed: true` would brick
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

| Agent | ambient | git-hook | ci-gate | pre-tool-use | managed-setting |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **Claude Code** | ✅ | ✅ | ✅ | ✅ | ✅ |
| **Cursor** | ✅ | ✅ | ✅ | ✅ | — |
| Copilot | ✅ | ✅ | ✅ | — | — |
| Codex | ✅ | ✅ | ✅ | — | — |
| Gemini | ✅ | ✅ | ✅ | — | — |
| Windsurf | ✅ | ✅ | ✅ | — | — |
| Devin | ✅ | ✅ | ✅ | — | — |
| Aider | ✅ | ✅ | ✅ | — | — |
| Grok | ✅ | ✅ | ✅ | — | — |
| Kimi Code | ✅ | ✅ | ✅ | — | — |
| Replit | ✅ | ✅ | ✅ | — | — |
| Tabnine | ✅ | ✅ | ✅ | — | — |
| VS Code | ✅ | ✅ | ✅ | — | — |
| Antigravity CLI | ✅ | ✅ | ✅ | — | — |

Claude Code is the reference target with the deepest enforcement primitives; the rest get the shared
hard floor plus advisory rules until their own native controls are wired in.

## Coverage levels

For each policy × agent, the compiler records one of five levels in `.chock/coverage.json`:

| Level | Meaning |
| :--- | :--- |
| **`enforced`** | An installed, hard, pre-execution in-agent control — a Claude PreToolUse hook wired into `.claude/settings.json`. |
| **`enforced-at-commit`** | The policy emitted a git-hook (installed automatically) or a CI gate whose workflow `install-ci` has actually written — hard at commit time or over the PR's commit range, advisory in-agent. |
| **`advisory`** | Only the ambient rule applies — compiled prose the agent is asked to follow. |
| **`unsupported`** | Nothing the policy emitted reaches this agent. |
| **`disabled`** | The policy is listed in `policies.disabled` and produces no artifacts or hooks. |

> **`enforced` is raised by the install step, not by `compile`.** Compiling writes a
> fragment; installing merges it into `.claude/settings.json` / `.cursor/hooks.json` and
> vendors the adapter that feeds the agent's JSON payload to the guard. Every `chock sync`
> runs that install step (`install-hooks` is its alias), so the documented adopter flow
> wires the guards it compiles. The claim is made by the step that performs the wiring, so
> it cannot get ahead of the mechanism. `ci-gate`'s contribution to `enforced-at-commit`
> follows the identical rule with `install-ci` in place of the hook installers.

> **The SessionStart arm hook is wiring, not a surface.** `chock sync` also installs a
> `SessionStart` entry (running the vendored `.chock/bin/sessionstart.py`) into
> `.claude/settings.json`. It carries no coverage claim: its only job is re-installing the
> git hooks on a fresh clone — git never clones them — or printing the `chock sync`
> command into the session context when it cannot. See
> [Arming a fresh clone](adopting.md#arming-a-fresh-clone).

Example for `protect-main-branch` (targets git-hook + CI + PreToolUse + managed-setting):

```json
{
  "protect-main-branch": {
    "claude":  "enforced",
    "cursor":  "enforced-at-commit",
    "copilot": "enforced-at-commit",
    "aider":   "enforced-at-commit"
  }
}
```

## How a policy picks its surfaces

A hook that must stop a command targets `git-hook` + `ci-gate` (the universal floor) and, where
available, `pre-tool-use` + `managed-setting`. A hook whose `on:` includes `tool_use` is compiled to
the `pre-tool-use` surface on agents that support it (Claude Code today). A best-practice rule with
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
