# Architecture

Chock has one job: let you **author a governance policy once** and **enforce it on every AI
coding agent** that touches your repo — your team's or a contributor's — with proof of
exactly where each guarantee holds.

<div align="center">
  <img src="assets/architecture.svg" alt="Author a policy once, compile it, and enforce it on every agent's native surface." width="820">
</div>

## The three stages

### 1. Author

A **policy** is a small, self-contained folder under `.agents/policies/<id>/`. Depending on its
`artifact` type it carries a manifest, an optional deterministic script, and an eval suite. One
policy is the single source of truth for one rule — you never copy it into per-agent config files.

### 2. Compile

`chock compile <id>` reads the policy and **emits the strongest control each target agent
supports**, across up to eight [enforcement surfaces](enforcement-surfaces.md):

- `git-hook` and `ci-gate` — the universal hard floor (every agent)
- `ambient-rule` — the compiled `AGENTS.md` block (advisory)
- `pre-tool-use` (Claude Code, Cursor) and `agent-hooks` (Copilot CLI, VS Code) —
  agent-native hard controls; `managed-setting` — compiled, not yet installed
- `gateway` — modeled for budgets/egress (future)

It also writes a **coverage report** (`.chock/coverage.json`) mapping every policy × agent to
`enforced`, `enforced-at-commit`, `advisory`, or `unsupported` — so a guarantee is never a guess.

### 3. Enforce

The compiled artifacts run where the agent actually operates: a **git hook** (pre-commit,
pre-merge-commit, and pre-push — clean merges are gated too) blocks a bad commit, a
**CI gate** re-runs the same check over a pull request's commit range — the un-bypassable backstop
for a hook skipped with `--no-verify` — and **Claude PreToolUse** stops a risky command *before* it
runs. The CI gate is wired up by `chock sync --ci`, not by `compile`: until that has run the
surface is compiled and inert, and the coverage report says so.
The git-hook shim calls the vendored **Python runner** (`.chock/bin/gate.py`), which
reads the compiled `gate.json` and executes the deterministic check. No `pip install` is needed on
the consumer machine — only a Python 3.11+ interpreter on PATH (the shim probes
`python3`/`python`/`py` for one that can import `tomllib`).

The CI gate runs the same runner in `--event ci` mode, diffing a PR's `base...head` range instead
of the (nonexistent, in a CI checkout) staged index. `chock sync --ci` writes the GitHub
Actions workflow that invokes it; the coverage report only credits `ci-gate` toward
`enforced-at-commit` once that workflow is actually present, the same check `pre-tool-use` already
gets — a control nothing wires up enforces nothing.

## Why "author once" matters

The AI-agent ecosystem is fragmented: Claude reads `CLAUDE.md`, Cursor reads `.cursor/rules`,
Copilot reads `.github/copilot-instructions.md`, and most agents read `AGENTS.md`. Worse, those files
hold **prose** an agent can ignore. Chock separates the **what** (your policy) from the
**where** (each agent's surface), and compiles the strongest *deterministic* control available on
each — falling back to advisory prose only when nothing stronger exists.

## Two-tier model: framework vs vendored runtime

```text
┌─────────────────────────────────────────────────────────────────────┐
│  Framework repo / package  (chock CLI, source of truth)     │
│  ┌────────────┐  ┌────────────┐  ┌─────────────┐  ┌──────────┐    │
│  │ scaffold   │  │ validate   │  │ compile     │  │ packs/   │    │
│  │ new/init   │  │ schemas    │  │ emitters    │  │ _skills/ │    │
│  └─────┬──────┘  └─────┬──────┘  └──────┬──────┘  └────┬─────┘    │
│        │               │                │              │          │
│        └───────────────┴────────────────┴──────────────┘          │
│                                    │                                │
│                         src/chock/gate/runner.py             │
│                                    │                                │
└────────────────────────────────────┼────────────────────────────────┘
                                     │ copied verbatim at compile time
                                     ▼
┌─────────────────────────────────────────────────────────────────────┐
│  Consumer repo  (no package install required at enforcement time)    │
│  .chock/bin/gate.py  ←──  vendored stdlib-only runner        │
│  .chock/compiled/<id>/git-hook/gate.json  ←── compiled gate  │
│  .git/hooks/pre-commit  ←── small shim that calls the runner        │
└─────────────────────────────────────────────────────────────────────┘
```

The **framework** side is the authoring and compilation toolchain — `packs/` holds the
authoring skills (`_skills/`), not baseline policies; the framework ships no policies. The **consumer** side is a
vendored, Python-3-only runtime that requires no pip install and no network at commit time.

## Pointer model

`AGENTS.md` holds a single managed pointer to `.agents/policies/INDEX.md`. `chock sync`
compiles every active rule (full text), every gate, and every skill into that index, capped by
`index.max_tokens` in `.chock/config.yaml`. `INDEX.md` is the ambient attention surface for
the agent; git hooks remain the guaranteed enforcement floor. The pointer is constant
so adapters never have to be rewritten when rules change.

## The components

| Component | Path | Role |
| :--- | :--- | :--- |
| **CLI** | `src/chock/cli.py` | One entry point; dispatches to each activity |
| **Scaffold** | `src/chock/scaffold/` | `init` / `new` / `install-skills` (deterministic) |
| **Compiler** | `src/chock/compile/` | Surfaces + per-surface emitters + coverage |
| **Validation** | `src/chock/validation/` | Spec/schema/budget/security/eval checks |
| **Registry** | `src/chock/registry/` | Artifact index + content hashes |
| **Lockfile** | `src/chock/lock.py` | Reproducible, hash-pinned installs |
| **Hooks installer** | `src/chock/hooks/` | Git dispatcher + policy wrappers |
| **Gate build** | `src/chock/gate/build.py` | Loads `hook.gate` from `manifest.yaml` and bakes `gate.json` |
| **Vendored runner** | `src/chock/gate/runner.py` | Self-contained runtime copied to `.chock/bin/gate.py` |
| **CI installer** | `src/chock/scaffold/install_ci.py` | Writes the GitHub Actions workflow that runs `ci-gate` |
| **Policies** | `.agents/policies/<id>/` | Installed from a catalog; owned by the adopter, never shipped |
| **Spec** | `spec/` | Neutral format, JSON schemas, enforcement matrix |

## Design principles

- **Deterministic-first.** If something can be a committed script, it is one. LLM steps are reserved
  for irreducible judgment (e.g. authoring new policy content via a skill).
- **Defense in depth.** Controls target a primary surface *and* a stronger backstop where possible
  (e.g. a git hook plus a Claude PreToolUse guard that refuses `--no-verify` before it runs, since
  `--no-verify` skips the hook).
- **Attestable.** Every control traces from a spec invariant → schema → check → template → CI (the
  "five-place rule"), and the coverage report makes enforcement auditable.
- **Cross-platform.** Declarative gates run through the vendored Python runner; hand-written guards
  still ship bash **and** PowerShell siblings. `.gitattributes` pins scripts to LF so hashes are
  byte-identical across operating systems.

## The CLI is a package manager, not a runtime

The deterministic parts (scaffold, compile, validate, install) live in the **CLI**. The generative
parts — authoring a bespoke policy from an interview — live in **skills** that the CLI *installs into
your own agent* and that your agent runs. Chock ships no LLM of its own.

See [Core Concepts](concepts.md) for the vocabulary and [Enforcement Surfaces](enforcement-surfaces.md)
for the coverage model in detail.
