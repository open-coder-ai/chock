# Chock methodology and architecture decisions

This file records the binding architecture decisions that govern the framework. Every decision here is enforced in code, schema, validator, or CI.

## D1 — Effects vocabulary

The `effects` array on any executing artifact uses exactly these classes:

| class | meaning | execution impact | approval required |
|---|---|---|---|
| `none` | read-only advisory; no side effects | none | no |
| `read_only` | reads repo/state but does not write | none | no |
| `reads_private` | reads private/sensitive data | none (informational for validators/adapters) | no |
| `writes_workspace` | writes files inside the workspace | git-state capture before execution | no |
| `writes_external` | writes outside the workspace (API, PR, git remote, etc.) | EFF-1 gate | yes |
| `irreversible` | cannot be undone without external undo | EFF-1 gate | yes |
| `network` | makes network calls | informational; network call checks in deterministic scripts remain SEC-2 | no |

Rules:
- `none` may not be mixed with any other class.
- Approval (`enforcement: verify\|block` and `approval.required: true`) is required only for `writes_external` or `irreversible`.
- `writes_workspace` triggers git-state capture before execution, but does not require approval.
- `read_only`, `reads_private`, and `network` are informational: they guide validators, adapters, and human reviewers but do not by themselves block execution.

## D2 — Agent-only execution

Chock is an agents framework. Every deliverable is agent-native: a skill, rule, hook, workflow, or subagent. There is no headless runtime engine and no standalone script or headless workflow artifact type. Multi-step coordination is expressed as a workflow skill whose `SKILL.md` describes the ordered procedure the agent follows. Deterministic scripts are allowed only as committed files under a code/hybrid skill, invoked by that skill.

## D3 — Identifying path inputs

A skill input is treated as a workspace path **only** when its `input_schema` property declares `"format": "workspace-path"`. Name-suffix heuristics are not used. Explicit schema annotation is the only safe signal.

Behavior:
- Values annotated as `workspace-path` are resolved against the workspace root.
- If the resolved path escapes the workspace root, the agent raises an actionable error naming the property, offending value, and root.
- All other values pass through byte-identical.

## D4 — Version

Framework version is **0.0.1** for the agent-only baseline. The taxonomy is intentionally smaller: no standalone script or headless workflow artifacts, no headless runtime, only agent-native deliverables.
