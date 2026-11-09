# How Chock compares

Chock compiles one policy into each agent's hooks, a git hook and a CI gate, and reports how strongly each holds; the tools below do some of that better, and some of it not at all.

Every claim about another tool links that tool's own README or docs, read on 2026-11-09. Every claim about Chock links a file in this repository. If a source changes, the source wins.

The "Chock adds" column rests on: the git hook and CI gate ([Enforcement Surfaces](enforcement-surfaces.md)), the agents the plugin builder targets ([README](../README.md)), rules that travel with a clone ([Why](why.md)), and the coverage report ([Concepts](concepts.md#coverage-level)).

| Tool | What it is, per its own docs | Where it runs | Stronger than Chock at | Chock adds |
| :--- | :--- | :--- | :--- | :--- |
| Plain agent hooks ([Claude Code](https://code.claude.com/docs/en/hooks), [Cursor](https://cursor.com/docs/hooks)) | The host's own hook API | In the agent | Everything the host offers, with no layer between | One policy for many agents; a commit and CI floor; a coverage report |
| Managed settings ([Claude Code](https://code.claude.com/docs/en/settings)) | Admin-deployed settings a user cannot override | In the agent, org-wide | Precedence: a user or project cannot override a managed key | Repo-level rules that travel with a clone; commit and CI gates |
| [Cupcake](https://github.com/eqtylab/cupcake) | Policy layer for AI agents, OPA Rego compiled to Wasm | In the agent | Richer in-session decisions, Rego, LLM-as-judge, MCP governance | Commit and CI gates; agents without hooks |
| [agentjail](https://github.com/LuD1161/agentjail) | Policy checks plus OS sandboxing | In the agent and the OS | An OS sandbox: Landlock, network control | Commit and CI gates; more agents |
| [Kastra](https://kastra.ai) | Authorization layer for AI actions | Cloud, self-hosted, air-gap, and on the laptop | Central allow/deny across prompts, tools, shell and APIs; signed audit trail | A local, repo-committed policy and commit and CI gates |
| [devleaps agent policies](https://pypi.org/project/devleaps-agent-policies/) | Policy server for Claude Code and Cursor hooks | In the agent, via a local server | A policy server whose policies return decisions and guidance per call | Commit and CI gates; more agents |
| [Prempti](https://github.com/falcosecurity/prempti) | Falco rules over agent tool calls | In the agent | Falco rules, a full audit trail, real-time visibility | Commit and CI gates; more agents |
| [Salt Code](https://getsaltcode.com/) | Security guidance injected into the agent's context | In the agent's context window | Breadth of agents; curated API, MCP and LLM security guidance | Gates that refuse, not advice |

## Where Chock is weaker

- **In-agent hooks are best-effort and fail open.** On Claude Code a crashed hook silently allows; Cursor is `enforceable`, because it can be told to fail closed; no agent reaches `enforced` today ([README](../README.md), [Concepts](concepts.md#coverage-level), [Coverage Levels](coverage-levels.md)).
- **Chock is not a security boundary.** Guards are pattern filters that quoting, aliases and encodings can evade; Chock is a governance layer, not a sandbox ([Assurance Case](assurance-case.md), [Baseline Policies](baseline-policies.md)).
- **Agents without hooks get advice in-session.** They read the compiled `AGENTS.md`; the rules are enforced at commit and in CI, not while the agent works ([Assurance Case](assurance-case.md), [Concepts](concepts.md#coverage-level)).
- **The commit gate can be skipped locally** (`--no-verify`); the CI gate is the backstop, and it holds only once it is a required status check ([Enforcement Surfaces](enforcement-surfaces.md)).
- **Chock does not install managed settings.** It compiles a `managed-settings.json` that nothing reads ([Enforcement Surfaces](enforcement-surfaces.md)).
- **MCP is thin.** A `tool_call` gate matches tool name and input text and does not understand what a tool does; the `mcp-gateway` credits no agent yet ([Agentic-Risk Coverage](agentic-risk-coverage.md), [Enforcement Surfaces](enforcement-surfaces.md)).

## Plain agent hooks

Claude Code hooks can allow, deny, ask, defer or rewrite a tool's input, and include prompt and agent hooks that ask a model; an error other than exit 2 lets the action go ahead unless the hook sets `onFailure: "block"` ([hooks](https://code.claude.com/docs/en/hooks)). Cursor hooks are fail-open by default, and `failClosed: true` blocks on crashes and timeouts too ([hooks](https://cursor.com/docs/hooks)). Chock writes these hooks for you, in each client's own dialect ([Enforcement Surfaces](enforcement-surfaces.md)), so it can be no stronger than the host; what it adds is one source for every agent and the gates at commit and in CI.

## Managed settings

In Claude Code nothing in a user's own settings files or `--settings` overrides a managed key, and managed settings arrive as a file, an MDM policy or server-managed settings ([settings](https://code.claude.com/docs/en/settings)). Cursor also has enterprise `hooks.json` paths and team hooks synced from a dashboard ([hooks](https://cursor.com/docs/hooks)). Where you control every machine, these are stronger than anything a repository can commit. Chock's rules live in the repo, so they reach contributors whose machines you do not manage ([Why](why.md)).

## Cupcake

Cupcake's README lists Rego policies compiled to Wasm; decisions to allow, modify, block, warn or require review, plus context injection; LLM-as-judge; and native MCP governance; for Claude Code, Cursor, Factory AI and OpenCode ([README](https://github.com/eqtylab/cupcake)). In-session, that is richer than Chock, whose gates `block`, `ask` or `warn` from regex, ref, allowlist or script checks ([Concepts](concepts.md)). The README does not mention commit or CI enforcement.

## agentjail

agentjail adds an OS sandbox when launched through `agentjail run`: Linux Landlock, network control, and a macOS proxy extension; it says "hooks alone are cooperative checks, not a filesystem isolation boundary", supports Claude Code, Codex and Cursor, and defers Windows ([README](https://github.com/LuD1161/agentjail)). Chock has no sandbox. For containment, use a sandbox; Chock can sit beside one.

## Kastra

Kastra describes itself as "the authorization layer for AI" that decides allow or deny before every prompt, tool call, shell command and API request, deployed in the cloud, self-hosted or air-gapped, with Kastra Edge for governance on the laptop; it names Claude Code, Codex CLI and Cursor, and offers signed, append-only audit traces ([kastra.ai](https://kastra.ai)). That is central, org-wide control Chock does not attempt.

## devleaps agent policies

devleaps runs a policy server that Claude Code hooks call, with Cursor in beta; policies yield decisions and guidance, and the default can be `ask` ([PyPI](https://pypi.org/project/devleaps-agent-policies/)). Chock has no server: the gate runs from the repo ([Concepts](concepts.md)).

## Prempti

Prempti evaluates every shell command, file read and write, web fetch and MCP call through the agent's hook, with Falco rules in YAML, allow, deny or ask verdicts, and a full audit trail, for Claude Code and Codex on Linux, macOS and Windows; it says it is "not a sandbox" ([README](https://github.com/falcosecurity/prempti)). Its visibility and audit trail go further than Chock's; Chock adds the commit and CI floor.

## Salt Code

Salt Code "injects security context into your agent's context window" for many agents and any MCP client, with guidelines for API, MCP, LLM and OpenAPI security ([getsaltcode.com](https://getsaltcode.com/)). That is guidance, like Chock's `advisory` tier; Chock's gates refuse at commit and in CI, and in the agent where it has hooks ([Concepts](concepts.md#coverage-level)).

## Use more than one

These tools mostly sit at different layers. A sandbox (agentjail), org-wide control (managed settings, Kastra) and richer in-session decisions (Cupcake) do not replace a gate at commit and in CI, and Chock does not replace them.
