# Agent Plugins

[Agent Plugins 1.0.0](https://agent-plugins.org) is an open, vendor-neutral standard for packaging
agent extensions, published on 2026-08-06 by OpenAI, Microsoft, Amazon, Cursor and Vercel, with
Google joining as a core maintainer. A plugin is a directory: `plugin.json` at its root, skills under
`skills/<name>/SKILL.md`, MCP servers in `mcp.json`, and reverse-domain namespace directories for
anything client-specific.

Chock policies are Agent Plugins.

```bash
chock plugin build --repo .
```

## What that claim means, exactly

**It means:** a policy folder is a valid plugin directory, and its advisory text loads in any
conformant client — VS Code, Copilot CLI, Cursor, Kiro, and anything else implementing the spec.

**It does not mean the policy is enforced there.** Agent Plugins v1 standardises two component
types, skills and MCP servers, and defines no enforcement mechanism whatsoever. Hooks, commands and
rules are [explicitly deferred](https://github.com/agentplugins/agent-plugins-spec) "until their
formats converge", and the specification is silent on trust, provenance and distribution.

So a packaged policy reaches exactly as far as an ambient rule: **advisory**. Every generated
`SKILL.md` says so in its own body, and packaging changes no value in `coverage.json` — a test
asserts that it cannot.

> Any conformant client can read a Chock policy. Only Chock makes it binding.

## Layout

Packaging is additive, which is the migration path the spec authors themselves recommend. Nothing
moves; `manifest.yaml` stays the single source of truth and `plugin.json` is generated from it.

```text
base/scan-secrets/
├── manifest.yaml              # canonical — hand-authored
├── evals/                     # unchanged
├── plugin.json                # generated
└── skills/scan-secrets/
    └── SKILL.md               # generated
```

`plugin.json` derives every field from the manifest — `name` from `id`, `license`, `repository` and
`author` from `provenance`, `keywords` from `artifact`, `enforcement` and any `compliance.owasp_asi`
tags. Nothing is invented, and no field is emitted where the manifest is silent.

The skill body comes from the same function that renders the `AGENTS.md` ambient block, reading the
*resolved* gate rather than the manifest's defaults. Set `chock.defaults.protected_branches`
to `[main, master, release/*]` and the packaged skill says so too — a policy that named different
branches in different places is how an adopter learns to distrust the tool.

## Why a `SKILL.md` and not just `plugin.json`

`plugin.json` is metadata. It carries identity, licence and provenance and **no capability at all**.
A plugin consisting only of a manifest is valid per the spec and completely inert: a client loads it
and gets nothing.

The spec defines exactly two component types that carry anything — skills and MCP servers. We ship
no MCP server, so `skills/<id>/SKILL.md` is the only slot in the format where a policy's content can
travel. Without it the package would announce a policy exists and never say what it is.

So the two files are not two descriptions of the same thing. `plugin.json` is the label on the tin;
`SKILL.md` is what is in it.

**Why every policy gets one, including the enforced ones.** Each policy already emits an ambient
rule into `AGENTS.md`, for a reason that applies just as well here: a commit-time gate fires *after*
the agent has written the code. Telling the agent the rule up front is what stops the work being
wasted, and the hook is what catches it when the agent ignores the text anyway. `SKILL.md` is that
same ambient rule in a form other clients can read — same source function, same two lines, same
resolved gate values.

That does mean an agent which reads both `AGENTS.md` and plugin skills may see a policy twice. It is
not straight duplication in practice, because `AGENTS.md` is always in context while skills load on
demand — but if you are tuning context budget, it is worth knowing the two surfaces overlap.

## The extension namespace

Enforcement metadata travels under `io.github.open-coder-ai`, which clients that do not implement it
are required by the spec to ignore:

```json
"extensions": {
  "io.github.open-coder-ai": {
    "manifest": "manifest.yaml",
    "artifact": "hook",
    "enforcement": "block",
    "coverage_without_chock": "advisory"
  }
}
```

That last field is named for the limitation rather than the capability. A client that ignores the
namespace gets advisory text and nothing else; one that implements it learns the policy is *capable*
of more, and where to look.

The spec says a client SHOULD base its namespace on a domain it controls. We do not own
`chock.dev`; we do control the GitHub organisation, so the reversed org handle is accurate
today. Moving it later breaks anything reading it, so it is pinned by a test rather than left to a
find-and-replace.

## Keeping it honest

`chock plugin build --check` reports stale or missing packaged output and exits non-zero
without writing anything. Run it in CI next to `recompile --check`; generated files that are
committed but unverified drift, and drift in a file other people's tools read is worse than drift in
one only we read.

That was the whole story for a while, and it was not enough. In an adopter repo, editing a policy's
`description` and running `recompile` left `plugin.json` describing the old policy while `validate`,
`recompile --check` and `eval` all exited 0 — four checks calling the repo clean, and the one that
caught it is a command nothing in the adopter flow mentions. `init`, `new policy` and the
`policy-init` skill emit no packaged output at all, so most adopters meet `plugin.json` only as a
file that a copied catalog policy brought with it.

So `validate` now carries a `plugin_drift` check. `validate` is what the installed pre-commit hook
runs, which is the point: the adopter learns at commit time, in the repo where it matters.

It is **opt-in by presence**. A policy with no `plugin.json` is not packaged and is not judged —
packaging is not a Surface (below), and this check must never be the reason a repo that never asked
for Agent Plugins starts failing. Copying a policy from the catalog opts you in, because the catalog
commits its packaged output, which is exactly the case where the drift would otherwise be silent.

Severity follows the same rule as compiled drift: under `--event commit`, drift the staged diff
never touched is a warning naming the fix rather than a block on someone who did not cause it.
Plain `validate` and CI stay strict.

## Why this is not an enforcement surface

The obvious implementation is a `Surface.AGENT_PLUGIN` registered beside `git-hook` and
`ambient-rule`. It would be wrong.

`Surface` is not a list of output formats. It is the input to `coverage_level()`, the function that
answers what a policy actually enforces on a given agent. Adding a format with no enforcement
semantics to that function either demands a per-agent matrix column for something that enforces
nothing, or inflates a coverage verdict — the exact overclaim
[`INSTALLED_SURFACES`](enforcement-surfaces.md) was rewritten to make structurally impossible.

Agent Plugins is packaging. Surfaces are enforcement. The separation is asserted by a test so it
cannot be quietly undone.

## Why `manifest.yaml` is still the source of truth

A fair question, since `plugin.json` now holds some of the same values: why keep two files rather
than authoring the plugin manifest directly?

Because only six scalars actually overlap — `name`, `version`, `description`, `license`,
`repository`, `author`. The plugin schema is `additionalProperties: false` with ten permitted keys,
and everything that makes a policy a policy — the gate spec, `effects`, `approval`, `mandatory`,
`lifecycle`, `security`, `changelog`, `compliance` — has no home among them. Authoring
`plugin.json` directly would push roughly nine tenths of every policy into
`extensions["io.github.open-coder-ai"]`, which the spec declares opaque: *"Agent Plugins assigns no
portable discovery, validation, loading, or failure semantics to client extension data."* The result
would look standardised while almost nothing about it was.

Three practical costs on top of that:

- **JSON has no comments.** The manifests here carry the defect history that produced them —
  `protect-main-branch` explains why its message uses `{refs}` — and that convention is load-bearing
  in this codebase.
- **Multi-line values become unreadable.** `scan-secrets`'s `content_pattern` is a YAML block
  scalar. As a single escaped JSON string it is far harder to review, in the file contributors are
  most likely to edit.
- **Coupling direction.** The standard is new. Generating `plugin.json` means dropping it later
  costs one module; authoring it means the policy format itself is welded to a v1 spec that may
  still move.

The duplication that remains is generated and verified by `plugin build --check`, so the two cannot
disagree. The failure mode worth avoiding is *two hand-maintained* manifests, which is exactly what
generation prevents.

**When to revisit.** The gate hides in our namespace only because Agent Plugins v1 has no hook or
rule component type. The spec defers those "until their formats converge", and
`FUTURE_CONSIDERATIONS.md` contemplates enforcement, provenance verification and plugin testing as
later work. If a standard component type for gates or rules lands, the gate moves out of the
namespace into the portable core, `manifest.yaml` shrinks to whatever remains, and collapsing to a
single file becomes real convergence rather than a cosmetic tidy-up. That is the trigger — not the
mere presence of two files.

## The hook-carrying vendor formats

The Agent Plugins 1.0 standard carries no hooks, so an `agent-plugins` package is advisory
by construction. Enforcement travels in four vendor plugin formats built from the same
policies (`chock plugin build --format claude|copilot|cursor|codex`), each published in its
own generated distribution repo and each **witnessed denying a destructive command on a
real install**:

| Vendor repo | Client(s) | Deny dialect |
| :--- | :--- | :--- |
| [chock-claude-plugins](https://github.com/open-coder-ai/chock-claude-plugins) | Claude Code | exit 2 |
| [chock-copilot-plugins](https://github.com/open-coder-ai/chock-copilot-plugins) | Copilot CLI, VS Code | exit 2 |
| [chock-cursor-plugins](https://github.com/open-coder-ai/chock-cursor-plugins) | Cursor | stdout `{"permission": "deny"}` |
| [chock-codex-plugins](https://github.com/open-coder-ai/chock-codex-plugins) | Codex (after its per-hook trust review) | exit 0 + `permissionDecision` JSON |

One guard, one adapter, byte-identical across all four — only the envelope each client
reads differs. The deny dialects are pinned by `tests/test_pretooluse_protocol.py` (every
case there reproduces a witnessed failure), and the probe evidence is recorded in the
0.4.0 CHANGELOG entry. Codex additionally installs every hook **untrusted** until a human approves
it, and that trust is bound to a hash of the hook command, so a plugin update silently
voids it until re-approved.
