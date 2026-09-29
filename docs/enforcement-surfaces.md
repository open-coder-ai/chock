# Enforcement Surfaces

A **surface** is *where* a compiled control runs. The same policy is emitted to the strongest surface
each agent supports — that's how "author once, enforce everywhere" stays honest about *how* strongly
each guarantee holds.

## The nine surfaces

| Surface | Determinism | Bypassable? | What it is |
| :--- | :--- | :--- | :--- |
| `git-hook` | Hard, at commit/push | Yes (`--no-verify`) | Pre-commit / pre-merge-commit / pre-push guard |
| `ci-gate` | Hard, un-bypassable | No, **once marked a required status check** -- see [the branch-protection gap](adopting.md#the-branch-protection-gap): the workflow file itself is tracked content a PR can delete, so `ci-gate`'s un-bypassable claim rests on a server-side branch-protection setting nothing in this repository can edit | The backstop for a skipped git hook |
| `ambient-rule` | Advisory | Yes | Compiled `AGENTS.md` block the agent is asked to follow |
| `pre-tool-use` | Hard, pre-execution | No | Blocks a command **before** the agent runs it, in each client's own deny dialect — every matrix-blocking vendor with a repo-level config (see the Cursor caveat) |
| `stop` | Hard, **post-execution** | No, but it fires after the tool calls it judges | Reads what the turn left in the worktree and refuses to end the turn. Credited with **no coverage word** -- see the backstop note below |
| `agent-hooks` | Hard, pre-execution | No | The same exit-2 deny for Copilot CLI + VS Code agent mode, from `.github/hooks/chock.json` (witnessed blocking on both, 2026-08-23). A content gate also gets a `PreToolUse` entry over `Edit\|Write` there (a top-level `permissionDecision` deny stopped an `Edit` in VS Code agent mode, 2026-09-28), and its turn-end gate is a `Stop` entry in the same file |
| `managed-setting` | Hard, org-level | No | Admin-deployed allow/ask/deny rules |
| `gateway` | Hard, un-circumventable | No | Budget/egress backstop — *modeled now, emitted later* |
| `mcp-gateway` | Hard, **MCP-routed tools only** | Yes (P3c) | A stdio proxy the client launches instead of the real MCP server; refuses matching `tools/call` payloads. Emitted today; **credits no agent** until the per-client config witness ships |

> **`stop` is a backstop, and is deliberately worth nothing.** It exists for what
> `pre-tool-use` structurally *cannot* see: a pre-tool hook is handed the tool call, so it
> matches only a recorded write vocabulary, and a heredoc or a redirect carries no file argument
> at all. A turn-end hook is handed nothing and reads the worktree, so it sees those bytes
> however they got there -- and it takes no matcher, so it wires **eight vendors** where the
> write path wires three.
>
> What it does not buy is coverage, and `coverage_cell` refuses it any (`UNCREDITED_SURFACES`).
> Every tool call in the turn has already run by the time it fires, so it cannot prevent a
> command, only refuse to end a turn that wrote something; and a crash, a kill or an exhausted
> context ends the turn without it running at all. Hence second line, behind the commit hook and
> CI, never a substitute -- and a policy reads the same word whether or not `stop` is wired.
> Because it reads the worktree, `applies_to.paths` is what keeps it off files the policy was
> never about; a pattern broad enough to hit documentation needs that bound first. A per-line
> `allowlist_pragma` is honoured here and at the write path only on a line already in HEAD: a
> human's committed waiver still counts, one the agent adds this turn does not (`WAIVABLE_EVENTS`
> are the staged events where any waiver counts). The agent that was refused is the one holding
> the pen. Only lines the turn changed against HEAD are judged, so an old violation in a touched
> file does not block the turn.
>
> **An agent's commit is not a human's.** The commit hook cannot ask who ran `git commit`, and an
> agent that can run it could add the waiver itself, so chock reads the environment the hook
> inherits from git. A commit is an agent's when `CHOCK_AGENT_COMMIT` is truthy (any value but
> empty, `0`, `false`, `no`, `off`), or `CLAUDECODE=1`, or `AI_AGENT` is non-empty, or a variable
> named under `agent_commit_env:` in `.chock/config.yaml` is set. The pre-commit gate then judges
> the commit at the event `agent-commit`: a waiver the commit adds is not honoured, one already in
> HEAD still is, and a refusal says which marker it saw. `CHOCK_AGENT_COMMIT=0` says "a person" and
> wins over every marker, for a person running git inside an agent's terminal; an agent could set
> it too, so it is a default and not an identity, and the guards on an agent's own commands are the
> separate backstop. Claude Code's two variables are witnessed reaching a git hook (a probe from
> the Bash tool, 2026-09-29); Codex, Cursor and Copilot markers are unverified, so add them once
> captured: `agent_commit_env: [CODEX_SANDBOX]`. Pre-push and CI are unchanged, and CI honours a
> waiver in the range it reads.
>
> **`action: warn | ask`.** A gate's `action` picks what a violation does (full table:
> `spec/gate-dsl.md`). `warn` never blocks: at commit, push and ci the reason is printed (a
> `::warning::` annotation in CI) and the exit is 0; in the agent it reaches Claude as PreToolUse
> `additionalContext` (other vendors have no verified channel, so they get stderr and the gate log),
> and at Stop it is a message to the user, never a block. `ask` puts the decision to a person: in
> the agent it is a `permissionDecision: ask` where the vendor honours one (the others deny); at
> commit and push, where no prompt is possible, it refuses unless a person runs that one command with
> `CHOCK_ALLOW=<policy-id>[,<policy-id>...]` and it is not an agent commit; in CI it is a warning. A
> policy whose only mechanism warns is not credited as enforcing in the coverage report; an ask is.

> **`agent-hooks` shell caveat, stated rather than glossed.** The surface genuinely
> enforces: it runs the guard before the tool call and honours exit 2 as deny (witnessed on
> both clients). On Windows, Copilot and VS Code run **PowerShell**, and before
> `block-destructive-commands` 0.0.6 the shipped guards were *bash-oriented* — they caught
> bash-syntax commands but not PowerShell-native destructive syntax. 0.0.6 closes that gap
> with a PowerShell/cmd guard matched against the raw command (`CHOCK_RAW_COMMAND`); other
> guards remain pattern filters, so the "non-standard shell" bypass class they document
> still applies to them. The hook runs through the launcher below, so the committed file is
> portable with no baked path.

> **Every in-agent hook runs through one committed launcher.** Each entry chock writes, on
> every vendor, is the same string -- read identically by bash, PowerShell and cmd.exe:
>
> ```
> git -c "alias.chock-hook=!test -f .chock/bin/launch.sh || { echo chock: no .chock/bin/launch.sh here, run chock sync --repo . >&2; exit 2; }; sh .chock/bin/launch.sh" chock-hook .chock/bin/<agent>.py [--guard|--gate "<repo-relative path>"]
> ```
>
> git runs the alias from the repository's top level, so relative paths resolve even when a
> session starts in a subdirectory. `.chock/bin/launch.sh` runs the first of
> `git config chock.python` (written to the clone's local `.git/config` by `chock sync`,
> never committed), `python3`, `python` and `py` that actually runs Python 3.11+ (the
> Windows Store `python3` stub, or a venv whose base Python is gone, is skipped). With none
> it exits 2 with a fix-it message -- never allow. With no launcher at git's top level (a
> nested repository, or a clone never synced) the command exits 2 the same way. Installed entries equal compiled ones exactly, so `chock sync` on any machine
> is a zero diff; entries in the old baked-interpreter form are recognised and replaced.

**`git-hook` + `ci-gate` are the universal hard floor** every agent shares. `pre-tool-use` and
`agent-hooks` are the premium tier on agents that expose native controls; membership
derives from agentseam's matrix (see the coverage matrix below).
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
> **fails open** on any other non-zero exit unless the hook entry sets `failClosed`. Chock's
> `beforeShellExecution` and `preToolUse` entries set `failClosed: true` (a hook that cannot
> start blocks); `stop` entries do not. With no interpreter baked into the entry, a fresh
> clone is not bricked: the launcher finds one or refuses with a fix-it message. The guard
> covers shell commands (`beforeShellExecution`); other tool classes are not intercepted.

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

| Agent | ambient | git-hook | ci-gate | pre-tool-use | stop | managed-setting | agent-hooks |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Claude Code** | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | — |
| **Cursor** | ✅ | ✅ | ✅ | ✅ | ✅ | — | — |
| Copilot | ✅ | ✅ | ✅ | — | ✅ | — | ✅ |
| Codex | ✅ | ✅ | ✅ | ✅ | ✅ | — | — |
| Gemini | ✅ | ✅ | ✅ | ✅ | ✅ | — | — |
| Windsurf | ✅ | ✅ | ✅ | ✅ | — | — | — |
| Devin | ✅ | ✅ | ✅ | ✅ | ✅ | — | — |
| Aider | ✅ | ✅ | ✅ | — | — | — | — |
| Grok | ✅ | ✅ | ✅ | ✅ | — | — | — |
| Junie | ✅ | ✅ | ✅ | — | — | — | — |
| Kimi Code | ✅ | ✅ | ✅ | — | — | — | — |
| Replit | ✅ | ✅ | ✅ | — | — | — | — |
| Tabnine | ✅ | ✅ | ✅ | ✅ | ✅ | — | — |
| VS Code | ✅ | ✅ | ✅ | — | ✅ | — | ✅ |
| Antigravity CLI | ✅ | ✅ | ✅ | ✅ | ✅ | — | — |

In-agent membership derives from agentseam's matrix: every adapted vendor whose row can block
a pre-tool call from a repo-level JSON hook config gets `pre-tool-use` (Copilot CLI and VS Code:
`agent-hooks`, chock's owned file). `stop` is derived the same way from the **turn-end** row, which
is a different question with a different answer: Grok and Windsurf can observe a finished turn
but not refuse one, so they are `detect` and get no column mark. Cursor cannot hold a turn either,
but its `stop` hook hands a refusal back to the agent as a `followup_message` (witnessed live on
3.21.18), which is `best-effort` and worth a mark: the agent is sent back to what the turn left
behind rather than the user being told after the fact. Copilot and VS Code refuse one too: their
`Stop` key in chock's own file was witnessed firing in VS Code agent mode (2026-09-28), and a block
answer made the agent carry on with the turn. It is registered under `Stop` alone, since `agentStop` fires
beside it and would run the gate twice; which of the top-level or nested block answers Copilot reads is
not isolated, so chock writes both. Junie and Kimi Code block only via home-level configs (Kimi
Code's in TOML), outside what `chock sync --repo` may write; Aider and Replit cannot block. A
checkmark is a wiring claim: new-vendor cells stay `witnessed: false` until a real client run is recorded.

## Coverage levels

For each policy x agent, the compiler records one level in `.chock/coverage.json`. The whole
vocabulary -- what each word means, the ladder order and the reasoning behind it, and the
evidence cap that bounds every grade -- is on its own page: **[Coverage Levels](coverage-levels.md)**.

## How a policy picks its surfaces

A hook that must stop a command targets `git-hook` + `ci-gate` (the universal floor) and, where
available, `pre-tool-use` + `managed-setting`. A hook whose `on:` includes `tool_use` is compiled to
the `pre-tool-use` surface on agents that support it (nine of them, Claude Code and Cursor
among them; Copilot
CLI and VS Code get the same guard via `agent-hooks`, and a content gate's write check as a `PreToolUse` entry over `Edit|Write` there). A best-practice rule with
no deterministic check compiles only to `ambient-rule`. The compiler always pairs a control with the
**strongest available backstop** — e.g. a git hook plus a CI gate, because a git hook alone can be
skipped with `--no-verify`.

## What happens when the guard cannot decide

The levels above grade the **outer** boundary: what the client does when chock's hook never
runs or dies outright. There is an inner one too — what the hook says when it *did* run and
could not reach a verdict — and the two answers are not the same. `gate/guard_runner.py`
distinguishes six such causes and answers only one of them with an allow.

| Cause | What chock returns | Why |
| :--- | :--- | :--- |
| The command will not tokenize (unbalanced quotes, trailing backslash, PowerShell quoting) | the guard's own verdict | The guard still runs: argv is a whitespace split (`CHOCK_ARGV_FALLBACK=1`) and `CHOCK_RAW_COMMAND` carries the exact string. `rm -rf / #'` is valid bash and invalid shlex, so a guard that reads the raw command must get the chance to refuse it. |
| The command is empty after tokenizing | allow | There is nothing to check. |
| No bash on the machine can resolve the guard | **ask** | No guard ran. The prompt names the fix: install Git for Windows (it ships bash), or put bash on PATH. |
| The guard the hook names is not on disk | **deny** | The hook config names it, so its absence is a broken install, not nothing to check. The reason says to run `chock sync --repo .`. |
| The guard crashed, exited a code that is none of 0, 1 or 3, or exited 1 with no reason or a traceback / syntax error | **ask** | The control was installed, reachable and runnable, and still produced no answer. (Exit 3 is not this: it is the guard asking on purpose, and its own first line is the prompt. Exit 1 blocks only with a reason on stderr, as `spec/script-backed-gates.md` states.) |
| The guard hit its 30-second timeout | **ask** | Same: the control ran and did not decide. |

A guard that fails refuses or asks; it never reports an allow it never established.

**What an `ask` becomes depends on the client, and no client turns it into a silent allow.**

| Client | Gate chock installs | An `ask` on the wire |
| :--- | :--- | :--- |
| Claude Code | PreToolUse, via the settings fragment `install-hooks` merges | `permissionDecision: "ask"` — prompts the user to confirm |
| VS Code agent mode / Copilot CLI | PreToolUse, via the agent-hooks file | `permissionDecision: "ask"` — forces a confirmation, and overrides the client's own auto-approve |
| Cursor | `beforeShellExecution`, via the Cursor hooks file | `{"permission": "ask"}` — honoured at this gate. Cursor's generic `preToolUse` accepts the value but does not enforce it, which is one reason chock installs the shell gate instead |
| Codex CLI (hand-wired only) | PreToolUse | **deny.** Codex's own parser rejects `ask` as unsupported and then fails open on the response it rejected, so agentseam's adapter degrades it to a deny rather than emit a value that would silently permit the call. A guard broken on every command therefore blocks on Codex where the others prompt |

Each row is cited to vendor source or vendor documentation at a named ref, so a reader can
recheck it rather than take this table's word:

- **Claude Code** — `code.claude.com/docs/en/hooks`, read 2026-08-31, `PreToolUse`
  `hookSpecificOutput` field table: *"`"ask"` prompts the user to confirm."* Claude Code is
  not open source, so this is documentation, not source.
- **VS Code agent mode** — `microsoft/vscode` at
  `718038e170df9c66a15087cebda424d9c7f051ff`,
  `src/vs/workbench/contrib/chat/browser/tools/languageModelToolsService.ts`.
  `resolveAutoConfirmFromHook` (`:877-930`) synthesises a confirmation and sets
  `allowAutoConfirm: false`; `:622-627` carries the comment *"A preToolUse hook that returned
  `ask` explicitly forces a confirmation, so never let `preApproved` override it."*
- **Cursor** — **not verified from a vendor artifact.** The claim rests on agentseam's
  recorded doc-basis verification (2026-08-26), which distinguishes `preToolUse` (accepts
  `ask`, does not enforce it) from `beforeShellExecution` (honours it). Second-hand, and
  labelled as such rather than presented as checked.
- **Codex CLI** — `openai/codex` at `32f48598a0609a882e5847f0d3e35d6d67f375bc`.
  `codex-rs/hooks/src/engine/output_parser.rs:458-460` returns *"PreToolUse hook returned
  unsupported permissionDecision:ask"*; `:144` computes a block reason only when nothing was
  rejected, and `codex-rs/hooks/src/events/pre_tool_use.rs:234-244` sets `should_block` in the
  non-rejected arm alone — so a literal `ask` there would let the call through.

**This raises no coverage grade.** A control is only as strong as its worst degradation, and
the empty command above still allows — so chock's in-agent controls stay at the level the
ladder gives a control that degrades to allowing until that grade is re-derived deliberately.

## Gate runner semantics

At commit time the vendored runner scans the staged files git reports as added, copied,
modified, renamed, or type-changed. It disables `core.quotePath` for its diff calls, so
non-ASCII paths arrive unescaped and are scanned like any other file. `dependency_allowlist`
gates match their watched manifest basenames (e.g. `package.json`) anywhere in the tree, not
only at the repo root. In CI range mode, a base ref that cannot be resolved fails **closed** —
the gate exits 2 rather than passing an unscanned range.
A compiled gate never judges chock's generated tree (`.chock/`) or its own policy's folder
(`.agents/policies/<id>/`): that folder's evals and references show the very content the gate
refuses, so judging them refused the policy's own adoption commit. Every other path, another
policy's folder included, is judged as before.

## Reading the coverage report

`chock compile <id>` (and `init`) write `.chock/coverage.json`, one `{"level", "basis",
"witnessed"}` cell per policy x agent. What each field means, and the evidence ceiling that
bounds every level, are on [Coverage Levels](coverage-levels.md#reading-the-coverage-report).
