# Chock — Developer Documentation

Everything you need to understand, use, and extend Chock. New here? Start with
[Getting Started](getting-started.md), then skim [Core Concepts](concepts.md).

> **Note for AI agents:** this folder is human documentation. Agents should read `AGENTS.md`
> for rules and `.agents/skills/<name>/SKILL.md` for skills — not `docs/`.

## 📖 Guides

| Guide | Read it to… |
| :--- | :--- |
| [Getting Started](getting-started.md) | Install, onboard a repo, and author your first policy |
| [Architecture](architecture.md) | Understand the *author → compile → enforce* model |
| [Core Concepts](concepts.md) | Learn the vocabulary: artifacts, manifests, surfaces, coverage |
| [CLI Reference](cli-reference.md) | Look up every command, flag, and example |
| [Authoring Policies](authoring-policies.md) | Write rules, hooks, skills, and subagents |
| [Enforcement Surfaces](enforcement-surfaces.md) | See the eight surfaces and the per-agent coverage matrix |
| [Agentic-Risk Coverage](agentic-risk-coverage.md) | Problem-first index: what Chock stops, at which honest tier — and what it doesn't |
| [Agent Plugins](agent-plugins.md) | Package policies for the open standard — and what that does not buy you |
| [Validation](validation.md) | Understand what `chock check` checks |
| [Registry & Lockfile](registry-and-lockfile.md) | Reproducible, hash-pinned distribution |
| [Compatibility](compatibility.md) | What may change between versions, and what pinning guarantees |
| [Reviewer Evidence](reviewer-evidence.md) | Recording what a review rests on, so the next reader can re-derive it |
| [Evals](evals.md) | Test policies with trigger, negative, behavior & adversarial cases |
| [Policies](baseline-policies.md) | What the base catalog offers, and how to install and customise it |
| [Adopting](adopting.md) | Fork, merge upstream, and keep consumer customizations safe |
| [Adapters](adapters/README.md) | Per-agent wrapper notes |

## 🧭 The 60-second mental model

1. You write a **policy** — a small folder with a manifest, an optional deterministic script, and evals.
2. `chock check` checks it against the **spec**.
3. `chock compile` turns it into the **enforcement surfaces** each agent supports
   (git hook, CI gate, Claude PreToolUse / managed-settings, `AGENTS.md` rule) and writes a **coverage report**.
4. `chock init` scaffolds the wiring — **no policies**; `chock add` installs each policy you choose from the catalog, and the **registry** and **lockfile** keep it reproducible.

## 🔗 Related references

- Root [`README.md`](../README.md) — project overview and quick start
- [`CONTRIBUTING.md`](../CONTRIBUTING.md) — how to contribute
- `spec/` — the neutral spec, JSON schemas, and enforcement matrix (source of truth for the format)
- `AGENTS.md` — the agent-readable rules compiled from policies
