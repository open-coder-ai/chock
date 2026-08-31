# Core Concepts

One page of vocabulary. Everything else in the docs builds on these terms.

## Policy

The unit of governance. A **policy** is a self-contained folder under `.agents/policies/<id>/` that
says "here is a rule, and here is how it's enforced and proven." Every policy has a `manifest.yaml`
manifest; depending on its type it also carries a script, a gate, and evals.

## Artifact types

The manifest's `artifact` field declares what kind of thing the policy is:

| Type | What it is | Ships with |
| :--- | :--- | :--- |
| `rule` | Always-on guidance compiled into `AGENTS.md` | `rule.text` in `manifest.yaml` |
| `hook` | A deterministic gate that blocks/allows an action | `hook.gate` in `manifest.yaml` (compiled to `gate.json`) |
| `skill` | A procedure an agent runs on demand | `SKILL.md` (frontmatter IS the manifest), `references/`, optional `scripts/` |
| `workflow` | A multi-step orchestration of skills/subagents | `workflow` block in `manifest.yaml` |

Those four are the complete set — `manifest.yaml` will not validate any other `artifact` value.

**Subagents are declared separately.** A scoped worker an agent can delegate to lives in its own
`subagent.yaml` under `subagents/`, validated by `subagent.schema.json`, which fixes
`artifact: subagent`. It is not one of the `manifest.yaml` artifact values above.

See [Authoring Policies](authoring-policies.md) for the manifest fields of each.

## Manifest

The `manifest.yaml` (or `subagent.yaml`) file. Beyond `id`, `name`, `artifact`, and `description`, key
fields include:

- **`enforcement`** — `advise`, `verify`, or `block` (how strict the policy is).
- **`effects`** — what the artifact does to the world: `read_only`, `writes_workspace`,
  `writes_external`, `irreversible`. Guards are `read_only`.
- **`approval`** — whether a human must approve before the *action* proceeds (never required for a
  read-only guard).
- **`provenance` / `lifecycle` / `trust_tier`** — authorship, `draft → review → production`, and how
  much the artifact is trusted (`sandbox` → `community` → verified).

## Gate

A hook's `hook.gate` in `manifest.yaml` selects a deterministic **kind** (`content_regex`, `forbidden_ref`,
`dependency_allowlist`), its `params`, the events it runs on (`on: [commit|push|tool_use]`), and the message
shown on block. `chock compile` flattens it to `gate.json`, which the vendored `.chock/bin/gate.py`
runner enforces at git-hook time. See [Gate DSL](../spec/gate-dsl.md).

## Enforcement surface

*Where* a compiled control runs. Chock models eight: `ambient-rule`, `git-hook`,
`ci-gate`, `pre-tool-use`, `agent-hooks`, `managed-setting`, `gateway`, `mcp-gateway`.
Different agents support different surfaces, `gateway`
is modeled but not emitted yet, and some surfaces need an explicit installer before they enforce
anything — see [Enforcement Surfaces](enforcement-surfaces.md).

## Coverage level

The strength of enforcement for one policy on one agent, written to
`.chock/coverage.json`. It reports what a policy **actually achieves**, not what the
agent is capable of: a surface that emits no file, or that nothing installs, raises no claim.

The four in-agent levels form an ordered ladder — `best-effort` ‹ `fail-to-ask` ‹
`enforceable` ‹ `enforced` — derived from the host's fail mode and the control's own
degradation. See [Enforcement Surfaces](enforcement-surfaces.md#coverage-levels) for the
ordering axis and why chock's own in-agent control sits at the bottom of it.

- **`enforced`** — a hard, pre-execution in-agent control that fails CLOSED: a crashed hook
  still blocks. No agent chock installs into offers this today.
- **`enforceable`** — installed and blocks, and can be told to fail closed but does not by
  default. Cursor's hooks are this tier.
- **`fail-to-ask`** — installed and blocks, and when the control cannot decide the action is
  put to a human rather than let through. Chock does **not** earn this: its guard degrades to
  allow. The level exists so a control stronger than ours can be graded as such.
- **`best-effort`** — installed and blocks, but fails OPEN: a crashed hook silently allows.
  An installed Claude Code PreToolUse hook is this tier. `chock sync` merges the compiled
  fragments into `.claude/settings.json` and only then raises the claim, so a policy is never
  reported as enforcing merely because a fragment was compiled.
- **`enforced-at-commit`** — hard at commit/CI time, advisory in-agent. This is the real
  enforcement floor today: a compiled `hook.gate` running from `.git/hooks/`.
- **`advisory`** — compiled into prose the agent is asked to follow.
- **`none`** — the agent supports none of the policy's emitted surfaces, or the only
  surfaces emitted are ones nothing installs.
- **`disabled`** — the policy is toggled off in `.chock/config.yaml` (`policies.disabled`);
  no artifacts are compiled and no hooks are installed for it.

## Eval

A test case for a policy, in `evals/suite.yaml`. Categories: `trigger` (should fire),
`negative_trigger` (should not fire), `behavior` (does the right thing), and adversarial (resists
bypass). See [Evals](evals.md).

## Registry

The index of every artifact in a repo (`.chock/registry.json`), including content hashes of
each deterministic script. Regenerated by `chock registry scan`.

## Lockfile

`chock.lock` — pins every installed pack by version and `sha256`. `chock check --only verify`
checks for drift.

## Config

`.chock/config.yaml` is the consumer-facing overlay for the installed policies:

```yaml
chock:
  version: "0.0.1"
  supported_agents: [claude, cursor, copilot]
  defaults:
    protected_branches: [main, master]

policies:
  disabled: [block-no-verify]
  overrides:
    scan-secrets:
      enforcement: advise
    protect-main-branch:
      surfaces: [ambient-rule]
```

- `policies.disabled` removes a policy's compiled artifacts and hooks without mutating the baseline.
- `policies.overrides.<id>.surfaces` sets the `targets` passed to `compile_policy`.
- `policies.overrides.<id>.enforcement: advise` is shorthand for `surfaces: [ambient-rule]`.

## INDEX.md

`chock sync` compiles every active rule (full `rule.text`), every gate, and every
skill into a single attention-budgeted file at `.agents/policies/INDEX.md`. `AGENTS.md` no
longer inlines those rules; it holds a managed pointer block that tells the agent to read
`INDEX.md` first. Rule delivery through `INDEX.md` is best-effort — the agent may or may not
read it — while git hooks are the guaranteed enforcement floor.

**No in-context mechanism is a guarantee, including inlining.** Agents auto-load their own
client file (`.claude/CLAUDE.md`, `.cursor/rules/*`), which points to `AGENTS.md`, which
points here — every step after the first depends on the agent choosing to follow the
pointer. This was verified by observation, not assumed. Inlining rules directly into
`AGENTS.md` would not change that, because `AGENTS.md` is not auto-loaded either.

The practical consequence for anyone adopting Chock: **if a requirement must always
hold, express it as a `hook`.** A rule is guidance an agent is asked to follow; only a hook
is a control that runs whether or not the agent cooperates. Treating a rule as an
enforcement boundary — especially for a compliance obligation — is the single most likely
way to misuse this framework.

## Catalog

Where policies live. The framework ships **mechanism only** — `chock init` installs no
policies — so a catalog is the source you copy from, and the copy is yours from that moment on.

The base catalog is [`chock-catalog`](https://github.com/open-coder-ai/chock-catalog),
laid out as `base/<policy-id>/`, with domain catalogs (`fintech/`, `healthcare/`, …) alongside.
Bundling policies with the framework would make them framework-owned, and therefore replaced on
upgrade — which is precisely what makes customisation impossible. See [Policies](baseline-policies.md).

## Adapter

The per-agent wrapper that points an agent at `AGENTS.md` (the compiled source of truth) in the
format that agent expects — `.claude/CLAUDE.md`, `.cursor/rules/*.mdc`, `.github/copilot-instructions.md`,
and so on. See [Adapters](adapters/README.md).
