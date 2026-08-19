# Roadmap

Direction is tracked publicly as issues labeled
[`roadmap`](https://github.com/open-coder-ai/chock/issues?q=label%3Aroadmap) — each
carries its rationale and acceptance criteria. This page is the narrative index;
the issues are the source of truth.

## Enforcement surfaces

- **MCP-gateway surface** ([#32](https://github.com/open-coder-ai/chock/issues/32)) —
  the largest available coverage jump: route MCP-capable agents' tool calls through a
  repo-governed gateway. Scope is exactly MCP-routed tool calls — shell commands and
  non-MCP tools stay at whatever tier their own surface earns — and the tier rises
  above `advisory` only with the same install witnesses as every other surface
  (gateway installed *and* the agent's MCP client configured to route through it).
- **More native pre-tool-use adapters** — agents gain a hook API, their tier rises
  without policy changes. Adapter contributions are a labeled
  [good first issue](https://github.com/open-coder-ai/chock/issues/11).
- **PreToolUse "ask" decision + a commit-message gate kind**
  ([#13](https://github.com/open-coder-ai/chock/issues/13)) — human-approval flows for
  policies where "a person decides" is the right answer.

## Evidence and limits

- **Tamper-evident gate log + resource-budget gate kind**
  ([#33](https://github.com/open-coder-ai/chock/issues/33)) — hash-chain the gate
  event log, then let rate/budget policies count against it.
- **Sigstore-signed catalog policies with install-time trust tiers**
  ([#15](https://github.com/open-coder-ai/chock/issues/15)) — provenance on top of
  today's hash pinning; installs that fail the configured tier fail closed.

## Not planned

- A policy language (Rego-style). Declarative manifests plus reviewable shell keep
  the honesty guarantee tractable; this is a deliberate scope limit.
- A hosted service. Chock is repo-local by design; the CI gate is the floor.

Weekly threat-intel digests (reviewed before merge) feed this roadmap:
[chock-threat-intel](https://github.com/open-coder-ai/chock-threat-intel).
