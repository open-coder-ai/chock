<div align="center">

<img src="https://raw.githubusercontent.com/open-coder-ai/chock/main/docs/assets/logo.svg" alt="Chock logo: a wheel held by a chock wedge" width="110">

# Chock

### Governance-as-code for AI coding agents. Write a rule once — every agent obeys it.

Your repo's rules become **deterministic guardrails** — for a team's private codebase or
a public open-source project — compiled to git hooks, CI gates,
native pre-execution hooks in **Claude Code, Cursor, Copilot CLI and VS Code**, and
`AGENTS.md` — read by Codex, Gemini, Aider and seven more. Not prose an agent can
ignore. Exit codes.

[![CI](https://github.com/open-coder-ai/chock/actions/workflows/ci.yml/badge.svg)](https://github.com/open-coder-ai/chock/actions/workflows/ci.yml)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](CONTRIBUTING.md)
[![PyPI](https://img.shields.io/pypi/v/chock)](https://pypi.org/project/chock/)
[![OpenSSF Scorecard](https://api.scorecard.dev/projects/github.com/open-coder-ai/chock/badge)](https://scorecard.dev/viewer/?uri=github.com/open-coder-ai/chock)
[![OpenSSF Best Practices](https://www.bestpractices.dev/projects/14155/badge)](https://www.bestpractices.dev/projects/14155)

[Quick start](#-quick-start) · [How it works](#-how-it-works) · [Policy catalog](https://github.com/open-coder-ai/chock-catalog) · [Docs](docs/README.md) · [Roadmap](#-roadmap)

*Featured in [awesome-ai-agent-governance](https://github.com/systempromptio/awesome-ai-agent-governance) -- accepted after the maintainer source-verified the enforcement claims.*

<img src="https://raw.githubusercontent.com/open-coder-ai/chock/main/docs/assets/demo.gif" alt="Terminal demo: chock init, chock add protect-main-branch, chock sync — then a commit straight to main is blocked, and a feature-branch commit passes" width="760">

*A real session, replayed. Install, adopt one policy, and the next commit straight
to `main` exits non-zero — no matter which agent, or which human, typed it.*

</div>

## Why

Your team runs five AI coding agents — and if your repo is open source, contributors
bring agents you never chose. Each has its own config file and its own idea of "the
rules." You write *"don't force-push to main"* into a `CLAUDE.md`, a
`.cursorrules` and a `copilot-instructions.md` — and an agent does it anyway, because
**prose is a suggestion, not a control**. Chock is the control: author a policy once, and
a compiler emits the strongest enforcement each agent actually supports, plus a coverage
report that tells you — honestly — where a guarantee holds and where it is only advice.

*Chock (rhymes with "block"): the wedge set against a wheel so it cannot roll until
someone deliberately removes it.*

## For open-source maintainers

AI broke the oldest balance in open source: contribution volume now scales with compute,
while review capacity still scales with maintainer hours. A contributor with an agent can
open ten large PRs in a weekend; you are still one human reading diffs. And you get no say
in which agent they bring — Claude Code today, Cursor tomorrow, something new next month.

What you do control is the repo itself, and Chock policies are **committed content**, so
your rules travel with every clone and fork — the maintainer governs the contributor's
*agent*, not just the contributor:

- **Every contributor's agent reads your rules with zero setup.** The compiled `AGENTS.md`
  and per-agent adapter files are in the tree; agents pick them up ambiently the moment
  the repo is cloned.
- **The repo re-arms itself.** Git never clones hooks, so Chock has the agent close the
  gap: an ambient rule tells every agent to run `chock sync --repo .` before its first
  commit, and for Claude Code a committed SessionStart hook arms the git hooks
  automatically when a session opens — consented through the workspace-trust prompt.
  The blocked commit happens on the contributor's machine, before the pull request,
  instead of in your review queue. [How arming works](docs/adopting.md#arming-a-fresh-clone).
- **The CI gate is yours and depends on nothing the contributor does.** `chock sync --ci`
  wires a commit-range gate into your pipeline, so a policy skipped or bypassed locally is
  still enforced on the PR.

Today the alternative is reviewing agent-written contributions with another agent, or by
hand — triage after the code already exists. With Chock the rules reach the contributor's
agent *before the code is written*, and what still arrives has already passed your gates:
**review the policy once, instead of every PR.**

## Highlights

- **✍️ Author once, enforce everywhere** — one policy → git hook + CI gate + native
  pre-execution hooks (Claude Code *and* Cursor) + `AGENTS.md`, across 13 agents. One
  `chock sync` wires all of it; the CI gate is opt-in (`chock sync --ci`) and
  [coverage only credits any surface once it is wired up](docs/enforcement-surfaces.md).
- **🛡️ Real guardrails, one command away** — `chock add protect-main-branch` pulls from
  the [catalog](https://github.com/open-coder-ai/chock-catalog): `scan-secrets`,
  `block-destructive-commands`, `block-no-verify`, an OWASP agentic-security pack, and
  more. Installed content is **yours to edit** — nothing upstream overwrites it.
- **⚙️ Deterministic, not vibes** — gates are declarative and run through a stdlib-only
  vendored runner; guard scripts are plain bash. No LLM calls, no network.
- **✅ Trust, but verify** — a validation engine, a hash-pinned `chock.lock`, and an eval
  suite (with adversarial cases) replayed against every policy's own mechanism on each build.
- **📊 Coverage you can prove** — a per-agent report grading every policy *enforced* /
  *enforced-at-commit* / *advisory*, so nobody believes the tooling does more than it does.
- **📦 Speaks the open packaging standard — and four vendor dialects** — `chock plugin
  build` emits [Agent Plugins 1.0.0](https://agent-plugins.org) packages any conformant
  client can read, plus hook-carrying plugin formats for
  [Claude Code](https://github.com/open-coder-ai/chock-claude-plugins),
  [Copilot](https://github.com/open-coder-ai/chock-copilot-plugins),
  [Cursor](https://github.com/open-coder-ai/chock-cursor-plugins) and
  [Codex](https://github.com/open-coder-ai/chock-codex-plugins) — each witnessed
  denying a destructive command on a real install.
  [What the badge does and does not mean](docs/agent-plugins.md).
- **🧩 One CLI, eight verbs** — `init` · `add` · `remove` · `sync` · `check` · `status` ·
  `enable` · `disable`. If you've used `uv` or `poetry`, you already know them.

## 🚀 Quick start

> **Requires:** Python 3.11+ and git; installed git hooks need bash at runtime.
> **Pre-1.0:** the CLI surface, manifest schema and compiled output can change between
> MINOR releases; PATCH releases never change compiled output (see [compatibility](docs/compatibility.md)).

```bash
pip install chock

cd /path/to/your/project
chock init .                     # wiring + authoring skills — no policies, no opinions

chock add protect-main-branch    # adopt a guardrail from the catalog
chock sync --repo .              # compile + install it
```

Now watch it enforce:

```bash
git checkout main
echo "oops" > hotfix.txt && git add hotfix.txt
git commit -m "quick fix straight to main"
# ❌ Direct commits/pushes to a protected branch (main|master) are blocked.
#    Create a feature branch and open a pull request.
#      - main

git checkout -b feature/x
git commit -m "on a feature branch"   # ✅ allowed
```

That branch list is resolved from the gate, not hard-coded: point
`chock.defaults.protected_branches` at `[main, master, release/*]` and the message says so.

`init` deliberately installs **no policies** — the framework ships mechanism; policies are
content you choose, and once installed they are yours to edit. That is what makes
customisation possible at all. New here? Follow the
[Getting Started guide](docs/getting-started.md).

> **`chock` not found?** Your Python scripts dir may not be on `PATH`. Use
> `python -m chock …` — it works regardless of PATH.

## 🔭 How it works

<div align="center">
  <img src="https://raw.githubusercontent.com/open-coder-ai/chock/main/docs/assets/architecture.svg" alt="Author a policy once, compile it, and enforce it on every agent's native surface." width="820">
</div>

You author a policy once. The compiler emits the strongest control each agent supports and
reports the exact coverage — *enforced*, *enforced-at-commit*, or *advisory* — so you
always know where a guarantee holds. Read the full
[architecture overview](docs/architecture.md).

## ✍️ Author your own policy

A policy is a small, reviewable manifest — the `hook.gate` block is what enforces, and a
blocking hook with no gate fails validation:

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

Chock is a **craft and enforcement framework first, and a security framework second** —
the framework ships mechanism, and `chock compliance report` scores whatever *your repo*
actually installs against four builtin control sets — `owasp_asi`, `mitre_atlas` (every
technique, from MITRE's machine-readable dataset), `nist_ai_rmf` (all 72 subcategories),
and `eu_ai_act` (the technical-obligation articles) — printing every `uncovered` row.
The [catalog](https://github.com/open-coder-ai/chock-catalog) carries the policies —
including a pack covering every control in the OWASP Top 10 for Agentic Applications —
and its README carries the coverage table with its exact `partial`/`full` honesty.

## 📚 Documentation

Full developer documentation lives in [`docs/`](docs/README.md) — start with
[Getting Started](docs/getting-started.md), then:
[Architecture](docs/architecture.md) ·
[Core Concepts](docs/concepts.md) ·
[CLI Reference](docs/cli-reference.md) ·
[Authoring Policies](docs/authoring-policies.md) ·
[Enforcement Surfaces](docs/enforcement-surfaces.md) ·
[Validation](docs/validation.md) ·
[Registry & Lockfile](docs/registry-and-lockfile.md) ·
[Evals](docs/evals.md) ·
[Policies](docs/baseline-policies.md) ·
[Adapters](docs/adapters/README.md)

## 🗺️ Roadmap

We're building in the open. Next up:

- [x] **`chock add <id>`** — install a policy or skill from any catalog, public or private.
- [x] **CI backstop** — `chock sync --ci` plus a commit-range gate mode, so a hook skipped with `--no-verify` is still caught on a pull request.
- [x] **Publish** — [PyPI package](https://pypi.org/project/chock/), attested releases.
- [ ] **Publish** — signed standalone binaries.
- [ ] **Upgrades** — `chock upgrade`, three-way merge against a pinned `chock.lock`.
- [ ] **Supply-chain & MCP packs** — block hallucinated ("slopsquatted") dependencies and un-approved MCP tools.
- [ ] **Cost & autonomy governance** — token/spend circuit-breakers and human-in-the-loop approval tiers.
- [ ] **Compliance attestation** — `chock attest` mapping controls to NIST AI RMF, ISO 42001 & the EU AI Act.

## 🤝 Contributing

We'd love your help — **code and non-code contributions alike**. Docs fixes, bug reports
and new policy ideas are all first-class. Start with the
[Contributing Guide](CONTRIBUTING.md) and the
[`good first issue`](https://github.com/open-coder-ai/chock/labels/good%20first%20issue) label.

Browsing the file tree? The adapter dot-directories (`.cursor/`, `.gemini/`, …) and root
stub files **are the product working** — this repo governs itself with the same wiring it
generates for adopters.

## ⭐ Star history

If Chock saves you from one bad `--force` push,
**[drop a star](https://github.com/open-coder-ai/chock)** — it's the single biggest signal
that helps other teams find the project.

<div align="center">
<a href="https://star-history.com/#open-coder-ai/chock&Date">
  <img src="https://api.star-history.com/svg?repos=open-coder-ai/chock&type=Date" alt="Star History Chart" width="600">
</a>
</div>

## 📄 License

Apache-2.0 — see [LICENSE](LICENSE). Built by and for teams shipping with AI agents.
