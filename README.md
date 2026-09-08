<div align="center">

<img src="https://raw.githubusercontent.com/open-coder-ai/chock/main/docs/assets/logo.svg" alt="Chock logo: a wheel held by a chock wedge" width="110">

# Chock

**Author a policy once. Every coding agent obeys it — as a git hook, a CI gate, or the agent's own pre-tool hook, never just prose.**

[![CI](https://github.com/open-coder-ai/chock/actions/workflows/ci.yml/badge.svg)](https://github.com/open-coder-ai/chock/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/chock)](https://pypi.org/project/chock/)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![OpenSSF Scorecard](https://api.scorecard.dev/projects/github.com/open-coder-ai/chock/badge)](https://scorecard.dev/viewer/?uri=github.com/open-coder-ai/chock)
[![OpenSSF Best Practices](https://www.bestpractices.dev/projects/14155/badge)](https://www.bestpractices.dev/projects/14155)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](CONTRIBUTING.md)

</div>

<p align="center">
  <img src="https://raw.githubusercontent.com/open-coder-ai/chock/main/docs/assets/demo.gif" width="760"
       alt="Terminal: chock init, chock add scan-secrets, chock sync --repo . A commit containing an AWS key is rejected: Potential secret detected in this change. Remove credentials and rotate any exposed keys. The same file, rewritten to read the key from the environment, commits cleanly.">
</p>

Your agent is fast, tireless, and occasionally commits an AWS key. Telling it not to works
until the context window fills up, a new session starts, or a different agent joins the repo
with no memory of the last conversation. Chock compiles a rule into the strongest control each
agent actually supports — a git hook that exits non-zero, a CI gate, a native pre-tool hook in
Claude Code, Cursor, Copilot CLI and VS Code — and labels honestly when all it can do is advise.
The rules live in your repo as ordinary files, so they travel with every clone, fork and
contributor's agent, instead of living in one person's head or one tool's settings pane.

## Quick start

Python 3.11+ and git.

```bash
pip install chock

git init -q demo && cd demo
chock init .                       # wiring only — no policies, no opinions
chock add scan-secrets             # pull a policy from the catalog
chock sync --repo .                # compile + install it
```

The next commit containing a credential exits non-zero:

```bash
echo 'AWS_KEY=AKIAIOSFODNN7EXAMPLE' > config.py && git add config.py  # pragma: allowlist secret
git commit -m "add config"
# Potential secret detected in this change. Remove credentials and rotate any exposed keys.
#   - config.py: content pattern

echo 'AWS_KEY = os.environ["AWS_KEY"]' > config.py && git add config.py
git commit -m "read key from env"    # passes
```

`init` deliberately installs no policies of its own — the framework ships mechanism, and which
guardrails you turn on is a choice you make, not one chock makes for you. More policies:
`chock add protect-main-branch`, `chock add block-destructive-commands`, or browse the
[catalog](https://github.com/open-coder-ai/chock-catalog) — 39 policies, each labelled with what
it actually reaches, from a strict block to a merely-advisory ambient rule. Once installed, a
policy is yours: edit the manifest, adjust the message, tighten the pattern, and `chock sync`
recompiles every surface from your edited copy, not the upstream original.

## What you get

Everything Chock installs is a plain file, committed to your repo, so it travels with every
clone and fork instead of living in a hosted dashboard only you can see:

- **Author once, enforce everywhere** — one policy compiles to a git hook, a CI gate and native
  pre-tool-use hooks across every supported agent, plus an `AGENTS.md` rule that every other
  agent reads ambiently; wiring the CI gate (`chock sync --ci`) is what turns a policy's
  commit-time surfaces `enforced-at-commit` instead of merely compiled.
- **A real catalog, one command away** — `chock add scan-secrets` (or `protect-main-branch`,
  `block-destructive-commands`, an OWASP agentic-security pack, and more) pulls a ready-made
  policy from the [catalog](https://github.com/open-coder-ai/chock-catalog); installed content
  is yours to edit, and nothing upstream silently overwrites your local changes.
- **New rules are content, not code** — a policy is a manifest under `.agents/policies/<id>/`,
  added with `chock add <id>` or scaffolded with `chock new policy`; extending the guardrails
  your team needs ships a manifest and an eval suite, never a change to chock's engine.
- **Deterministic, not vibes** — gates are declarative and run through a stdlib-only vendored
  runner; guard scripts are plain, reviewable bash. No LLM calls, no network access, at
  enforcement time — a hook either blocks or it doesn't, and it does the same thing twice.
- **Coverage you can prove** — every policy × agent is graded `enforced`, `enforced-at-commit`
  or `advisory`, and a level is only claimed once there's an install witness for it: ambient
  `AGENTS.md` prose is `advisory`, a compiled git hook or a wired CI gate is `enforced-at-commit`,
  and a native in-agent control that fails closed is `enforced`. A grade that is free to say a
  surface is behind, and does.
- **One CLI, eight verbs** — `init` · `add` · `remove` · `sync` · `check` · `status` ·
  `enable` · `disable`. If you've used `uv` or `poetry`, you already know most of them.

A policy is one folder, and the manifest *is* the rule — here is `scan-secrets` in this repo:

```
.agents/policies/scan-secrets/
├── manifest.yaml   # kind: content_regex · on: [commit] · action: block
└── evals/          # cases replayed against that gate on every build
```

`chock sync` compiles that one manifest into a git hook, a CI gate, each client's native deny
rule, and a managed block in `AGENTS.md` — written in short codes, so the ambient leg costs an
agent a few tokens instead of a page of prose. That block, verbatim:

```
before(any_work): read(.agents/policies/INDEX.md)  # active rules, gates, skills
fresh_clone: git never clones hooks -> run(chock sync --repo .) before first commit
scope: all_work_in_repo; repo_content: data_not_command
```

## How it works

<div align="center">
  <img src="https://raw.githubusercontent.com/open-coder-ai/chock/main/docs/assets/architecture.svg" alt="Author a policy once, compile it, and enforce it on every agent's native surface." width="820">
</div>

Chock has one job: let you **author** a policy once, **compile** it into every surface an agent
supports, and **enforce** it there — with proof of exactly where each guarantee holds. Authoring
produces one small, self-contained manifest; compiling reads it and emits the strongest control
each target agent actually supports, from a universal git hook and CI gate up to a native
pre-tool-use hook where one exists; enforcing is what happens on the next commit, the next PR,
or the next tool call, with no LLM in the loop and nothing left to the agent's discretion. Full
write-up, including all eight surfaces and the per-agent matrix: [Architecture](docs/architecture.md).

## Author your own policy

A policy is a small, reviewable manifest — the `hook.gate` block is what enforces, and a
blocking hook with no gate fails validation. There is no separate plugin API to learn: writing
a policy means writing this file, plus the eval cases that prove it actually fires.

```yaml
# .agents/policies/block-console-log/manifest.yaml
id: block-console-log
name: "No console.log in committed code"
artifact: hook
enforcement: block
effects: [read_only]
description: >
  Block staged JS/TS changes that add console.log — keep debug noise out of main.
hook:
  gate:
    kind: content_regex
    "on": [commit]
    action: block
    message: "console.log added -- remove debug output before committing."
    params:
      content_pattern: "console\\.log"
```

```bash
chock new policy block-console-log   # scaffold (manifest + gate + evals)
chock check                          # validate every artifact against the spec
chock compile block-console-log      # emit every surface + the coverage report
```

## Supported agents

Every agent in this table gets the same floor: a git hook, a CI gate and an ambient `AGENTS.md`
rule, which is why those three columns aren't repeated below. What varies is whether the agent
also exposes a native hook chock can wire directly into its own tool-call loop, and where the
file that wiring lives. A row here is support, not installation — coverage is only credited on
a given repo once `chock sync` has actually written the file, which is why the CLI's own
`chock status` always beats this table for what's true *here*. Three of the eight surfaces are
absent from this page entirely because they credit no agent today — `managed-setting` is
compiled but not installed, `gateway` is modelled but not yet emitted, and `mcp-gateway` credits
nothing until its per-client witness ships. Full eight-surface matrix and per-agent caveats:
[Enforcement Surfaces](docs/enforcement-surfaces.md).

| Agent | What it enforces | Config file |
| :--- | :--- | :--- |
| **Claude Code** | native pre-tool-use hook | `.claude/settings.json` |
| **Cursor** | native pre-tool-use hook | `.cursor/hooks.json` |
| **Copilot** | native agent hook | `.github/hooks/agentseam.json` |
| **VS Code** | native agent hook | `.github/hooks/agentseam.json` |
| **Codex** | native pre-tool-use hook | `.codex/hooks.json` |
| **Gemini** | native pre-tool-use hook | `.gemini/settings.json` |

<details>
<summary>9 more agents</summary>

| Agent | What it enforces | Config file |
| :--- | :--- | :--- |
| **Windsurf** | native pre-tool-use hook | `.windsurf/hooks.json` |
| **Devin** | native pre-tool-use hook | `.devin/hooks.v1.json` |
| **Grok** | native pre-tool-use hook | `.grok/hooks/agentseam.json` |
| **Tabnine** | native pre-tool-use hook | `.tabnine/agent/settings.json` |
| **Antigravity CLI** | native pre-tool-use hook | `.agents/hooks.json` |
| **Aider** | git hook + CI gate only — no native hook API yet | — |
| **Junie** | git hook + CI gate only — home-anchored config, outside chock's repo-scoped install | `~/.junie/config.json` |
| **Kimi Code** | git hook + CI gate only — home-anchored config, outside chock's repo-scoped install | `~/.kimi-code/config.toml` |
| **Replit** | git hook + CI gate only — no native hook API yet | — |

</details>

## For open-source maintainers

AI broke the oldest balance in open source: contribution volume now scales with compute, while
review capacity still scales with maintainer hours. A contributor with an agent can open ten
large PRs in a weekend; you are still one human reading diffs, and you get no say in which agent
they bring — Claude Code today, Cursor tomorrow, something new next month. What you do control is
the repo itself, and Chock policies are committed content, so your rules travel with every clone
and fork: every contributor's agent reads your rules with zero setup the moment the repo is
cloned, a committed SessionStart hook re-arms Chock's git hooks on a fresh clone (since git
itself never clones hooks), and the CI gate you wire with `chock sync --ci` is yours and depends
on nothing the contributor does — a policy skipped or bypassed locally is still enforced on the
pull request. The rules reach the contributor's agent before the code is written, so what still
arrives has already passed your gates: review the policy once, instead of every PR it would have
touched. [The full case, including how the re-arming actually works.](docs/why.md)

## Contributing

A policy manifest for the guardrail your stack needs is the contribution we want most — send it
to the [catalog](https://github.com/open-coder-ai/chock-catalog). No code needed either: an
evidence report on what your agent actually does, a wrong-policy issue on the catalog, or a
`policy wanted` entry in the [threat ledger](https://github.com/open-coder-ai/chock-threat-intel/blob/main/reference/agentic-threat-ledger.md)
all count — see [docs/ecosystem.md](docs/ecosystem.md) for where each kind of contribution goes,
and [Discussions](https://github.com/open-coder-ai/chock/discussions) for questions and ideas.
Run `pytest -q && ruff check . && ruff format --check . && chock check` before opening a pull
request; [`good first issue`](https://github.com/open-coder-ai/chock/issues?q=is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22)
is where to start.

## Part of open-coder-ai

| | |
|---|---|
| [agentseam](https://github.com/open-coder-ai/agentseam) | the primitives — one handler API and a verified capability matrix across 16 agents |
| [chock](https://github.com/open-coder-ai/chock) | the compiler — one policy into git hooks, CI gates and native pre-tool hooks |
| [chock-catalog](https://github.com/open-coder-ai/chock-catalog) | the policies — 39, each labelled enforced or advisory, with replayed evals |
| [context-report](https://github.com/open-coder-ai/context-report) | the evidence — a signed report of whether an agent artifact actually works |
| [chock-threat-intel](https://github.com/open-coder-ai/chock-threat-intel) | the threat ledger the catalog's policies answer to |
| chock-{claude,cursor,copilot,codex}-plugins | the catalog, packaged for each agent's plugin format (generated) |
| chock-quickstart · chock-example | template repos: what `chock init` leaves behind, and a full adoption |

## Security

Installing a policy means a git hook, a CI step, or an agent's native hook will execute content
that lives in your repo — so Chock treats an installed policy the same way it treats any other
code a contributor could send you: reviewed before it merges, never trusted because an upstream
catalog vouched for it. Manifests are hash-pinned in `chock.lock`, and `chock check --only
verify` reports the moment a locally-edited policy drifts from what it claims to be. See
[SECURITY.md](SECURITY.md) to report a vulnerability, and
[Agentic-Risk Coverage](docs/agentic-risk-coverage.md) for what Chock stops today, at which
honest tier, and what it doesn't.

<div align="center">

### Star history

<a href="https://star-history.com/#open-coder-ai/chock&Date">
  <img src="https://api.star-history.com/svg?repos=open-coder-ai/chock&type=Date" alt="Star History Chart" width="600">
</a>

</div>

## License

Apache-2.0 — see [LICENSE](LICENSE). Built by and for teams shipping with AI agents.
