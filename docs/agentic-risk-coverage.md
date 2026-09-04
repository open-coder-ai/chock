# Agentic-Risk Coverage

This page answers the question people actually search — *"can something stop my AI agent
from doing X?"* — one row per problem, each stating the mechanism Chock ships and the
tier it honestly earns **today**. Rows that read `advisory`, `planned`, or `out of
scope` stay on this page on purpose: a coverage claim you cannot verify is worse than a
gap you know about. The enforcement levels — `enforceable`, `best-effort`,
`enforced-at-commit`, `advisory` — are the compiler's own coverage taxonomy (see
[Enforcement Surfaces](enforcement-surfaces.md#coverage-levels)); `planned` and `out of
scope` are statuses of this page, not compiler output. An enforcement level is claimed only
with an install witness, never because a fragment was merely compiled.

Rows on this page used to read `enforced` for an installed in-agent control. They do not any
more, and the change is a correction rather than a regression: `enforced` means a hook that
still blocks when it dies, and no agent Chock installs into offers that. An installed
in-agent guard reads `best-effort` (Claude Code, Copilot CLI, VS Code agent mode — the host
fails open) or `enforceable` (Cursor — the host can be told to fail closed). The ladder also
carries `fail-to-ask`, for a control that puts the action to a human when it cannot decide;
Chock's guard degrades to allow, so no row here earns it.

## The tiers

| Tier | Meaning |
| :--- | :--- |
| `enforceable` | A control runs **before** the action, inside the agent (`pre-tool-use`, `agent-hooks`), with an install witness, on a host that can be told to fail closed — Cursor today. `managed-setting` would be hard too but is deliberately excluded until an install witness exists for it: the compiler credits no surface it cannot witness |
| `best-effort` | The same in-agent control on a host that fails OPEN when the hook dies — Claude Code, Copilot CLI, VS Code agent mode. It blocks what it sees; a crashed hook silently allows, and that is stated rather than rounded up to `enforced` |
| `enforced-at-commit` | A deterministic gate at commit/push (`git-hook`) with the `ci-gate` backstop — the action happened, the artifact cannot land |
| `advisory` | Compiled rule text the agent is asked to follow — persuasion, not prevention, and labeled as such |
| `planned` | Page-only status: a public [roadmap](roadmap.md) issue exists; nothing is claimed until it ships with witnesses |
| `out of scope` | Page-only status: a deliberate non-goal — stated plainly, with a pointer to the layer that owns it |

## The problems, in the words people search

| "Can Chock stop…" | Mechanism | Coverage today |
| :--- | :--- | :--- |
| …my agent running `rm -rf` / destructive commands? | `block-destructive-commands` | `best-effort` on Claude Code (`pre-tool-use`) and Copilot CLI + VS Code agent mode (`agent-hooks`, PowerShell-native guard since 0.0.6) — those hosts fail open when the hook dies; `enforceable` on Cursor via the stdout deny response, with the fail-open caveat stated in [Enforcement Surfaces](enforcement-surfaces.md); `enforced-at-commit` floor on every agent |
| …secrets and `.env` contents landing in commits? | `scan-secrets` gate | `enforced-at-commit` + CI backstop. Runtime exfiltration over the network is **not** claimed — the `egress_allowlist` gate governs MCP-routed calls only and credits no agent until its per-client witness ships ([#32](https://github.com/open-coder-ai/chock/issues/32)) |
| …prompt injection hidden in repo content? | `block-invisible-unicode` gate; `injection-defense` rule | Invisible/direction-override Unicode: `enforced-at-commit`. The broader instruction-in-content class: `advisory` (`data_not_command`) — no deterministic gate can read intent |
| …an agent editing or disabling its own guardrails? | `protect-agent-config` | `best-effort` (`enforceable` on Cursor) where a pre-execution surface exists; `advisory` elsewhere; regeneration only via `chock sync` |
| …a malicious policy or skill entering my repo? | `chock.lock` hash pinning, catalog provenance, Sigstore-signed releases | Hash **recorded** at install and drift **detected** by `chock check`; install-time *rejection* happens only when `chock add --verify-sha` supplies the expected hash — stated plainly rather than rounded up to enforcement. Signed catalog trust tiers: `planned` ([#15](https://github.com/open-coder-ai/chock/issues/15)); AI-BOM emission: `planned` ([#57](https://github.com/open-coder-ai/chock/issues/57)) |
| …tool calls with dangerous arguments (path traversal, root deletes)? | shell slice via `block-destructive-commands`; structured-argument validation | Shell slice: `best-effort`/`enforceable` as above. General tool-argument constraints: `planned` ([#58](https://github.com/open-coder-ai/chock/issues/58)) |
| …an agent poisoning its own long-term memory? | `memory-discipline` | `advisory` — and deliberately so here: write-path memory enforcement is a different system than a repo-scoped framework, and this page does not claim it |
| …direct pushes to `main`, `--no-verify`, force-pushes? | `protect-main-branch` gate, `block-no-verify`, `git-safety` | `enforced-at-commit` (gate); the never-bypass-hooks discipline itself: `advisory` backed by the CI gate, which re-runs `chock check` on the PR head regardless of what was skipped locally |
| …wildcard permission grants in agent config? | `block-wildcard-agent-permissions` gate | `enforced-at-commit` |
| …an agent deleting tests or assertions to get green? | `test-integrity` gate, `agent-discipline` (`assertion_deletion: block`) | `enforced-at-commit` (gate) — blocks a deleted test file, a net loss of assertions across the change, or a vacuous assertion (`assert True`, `expect(true)`) added in their place; re-checked in CI on the PR head via the `ci-gate` backstop, so it holds for an inbound contributor whose agent never ran a hook. The pragma `chock: test-removal-reviewed` on the removing line is the reviewed escape hatch. No `pre-tool-use` binding exists, so this is not claimed at the in-agent tier. The ambient rule text remains `advisory` |

## Against the OWASP Top 10 for Agentic Applications

| Risk | Status | Mechanism |
| :--- | :--- | :--- |
| ASI01 Agent Goal Hijack | partial | `block-invisible-unicode` (`enforced-at-commit` slice) + `injection-defense` (`advisory`) |
| ASI02 Tool Misuse | partial | `block-destructive-commands` (in-agent slice at `best-effort`/`enforceable`, `enforced-at-commit` floor); [#58](https://github.com/open-coder-ai/chock/issues/58) extends to structured arguments |
| ASI03 Identity & Privilege Abuse | out of scope | Identity providers and credential brokers own this layer; Chock governs repo-scoped behavior, not credentials |
| ASI04 Agentic Supply Chain | partial | Hashes recorded at install, drift detected by `chock check`, rejection only with `chock add --verify-sha`; Chock's own releases are Sigstore-signed. Signed-catalog trust tiers and AI-BOM: `planned` ([#15](https://github.com/open-coder-ai/chock/issues/15), [#57](https://github.com/open-coder-ai/chock/issues/57)) |
| ASI05 Unexpected Code Execution | partial | `code-safety` (`advisory`: no `eval`/`exec`, verify dependencies) + destructive-command gates (in-agent slice at `best-effort`/`enforceable`) |
| ASI06 Memory & Context Poisoning | advisory | `memory-discipline`, `context-hygiene` — stated honestly: efficiency-oriented, not a poisoning defense |
| ASI07 Insecure Inter-Agent Comms | out of scope | Runtime message inspection belongs to the orchestration platform |
| ASI08 Cascading Failures | partial | `block-destructive-commands` catches observed sabotage-class operations; systemic containment is the platform's |
| ASI09 Human-Agent Trust Exploitation | out of scope | Model-layer behavior; no deterministic repo gate can claim it |
| ASI10 Rogue Agents | partial | `protect-agent-config` + kill discipline via gates; runtime fleet control is out of scope |

The weekly [threat-intel digests](https://github.com/open-coder-ai/chock-threat-intel)
track this taxonomy against the catalog and generate the `policy wanted` rows that feed
the roadmap.

## What Chock does not do — stated plainly

- **Agent identity, tokens, and spend budgets.** Identity platforms and gateways own
  runtime credentials and quotas. Chock's `gateway` surface is reserved for repo-scoped
  budget/egress backstops and claims nothing today.
- **Runtime semantic filtering between agents.** Judging message intent mid-loop puts a
  model in the enforcement path; Chock's position is deterministic checks or honest
  `advisory`, never probabilistic "enforcement."
- **Passive endpoint telemetry.** Watching an agent after the fact is an EDR product's
  job; Chock's value is the deterministic slice *before* commit, push, or execution.
- **Model-layer failures.** Judgment, tone, and social behavior cannot be gated from a
  repo. Rules cover the expressible slice as `advisory`, and this page will not dress
  that up as enforcement.

If a row here ever disagrees with what the compiler reports for your repo, the compiler
is right and this page has drifted — please [open an issue](https://github.com/open-coder-ai/chock/issues).
