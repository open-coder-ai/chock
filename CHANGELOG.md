# Chock changelog

## Unreleased

MINOR: plugin packaging output changes (spec fixes and three new formats), and the
vendored PreToolUse adapter changes -- the deny-dialect and payload-decoding fixes below
mean an adopter's next `chock sync` rewrites it. Every other compiled enforcement
surface is unchanged.

- **`cursor` and `codex` plugin formats**: `chock plugin build --format cursor|codex`
  packages a policy for Cursor and OpenAI Codex, with the enforcing hook each vendor
  actually reads. Same guard, same adapter, byte-identical to every other format --
  only the envelope differs. `--format all` now emits five trees.
  - **Cursor** (`.cursor-plugin/plugin.json` + flat `hooks/hooks.json`) subscribes to
    `beforeShellExecution`, the shell-scoped event `chock sync` already installs, so a
    plugin install and a repo install run the identical hook. No `matcher` is emitted:
    under this event the matcher is a regex over the COMMAND TEXT, not a tool name, so
    the other formats' `"Bash"` would match almost nothing and silently disable the
    guard. Cursor ignores Agent Plugins hooks entirely, so this is the only format that
    enforces there.
  - **Codex** (`.codex-plugin/plugin.json` + nested `hooks/hooks.json`) subscribes to
    `PreToolUse` with matcher `Bash` -- Claude's protocol exactly. The legacy
    `.codex-plugin/` manifest is deliberate: Codex's loader DISCARDS hooks from an
    Agent-Plugins-format manifest (`codex-rs/core-plugins/src/loader.rs`), so shipping
    the Copilot package there would install a plugin whose enforcement is deleted at
    load time while its description still claimed it.
- **Codex packages claim witnessed enforcement -- via JSON deny, not exit codes.**
  Probed on a real Codex Desktop install (Windows 11): a trusted PreToolUse hook
  returning the documented exit-2 deny ran the command three times, because Codex wraps
  Windows hook commands in `powershell -Command`, which collapses exit 2 into 1 -- and
  Codex's parser treats that as a failed hook and FAILS OPEN (its only stdout-parsing
  arm is exit 0). With the deny carried in `hookSpecificOutput.permissionDecision` JSON
  on a clean exit, the same command was witnessed BLOCKED (2026-08-24). The adapter now
  speaks that dialect to Codex-shaped payloads (`turn_id` present); Claude Code keeps
  its witnessed exit-2 path. Conditions stated in the package posture: Codex hooks are
  UNTRUSTED on install until a human approves a per-hook trust review, that trust is
  bound to a hash of the hook command so a plugin update silently voids it until
  re-approved, and every hook failure fails open. The emitted hooks.json also carries no
  top-level `description`: Codex < 0.143.0 rejects the whole file over that one key and
  silently drops every hook in it (openai/codex#30397).
- **Cursor packages DO claim enforcement**, witnessed blocking on a real install after the
  two fixes below, with a benign command in the same session still allowed.
- **Two silent fail-opens fixed, both found by probing a real Cursor install** (neither
  is visible in any documentation, and each would have shipped a package that advertised
  enforcement and delivered none):
  - **Payload decoding.** Cursor prefixes its hook payload with a UTF-8 BOM, and
    `sys.stdin.read()` decoded those bytes with the platform locale (cp1252 on Windows),
    turning the BOM into three stray characters. `json.loads` then failed, the adapter
    reported "not checked", and returned 0 -- every command ALLOWED. The payload is now
    read as bytes and decoded `utf-8-sig`, which also stops non-ASCII paths being mangled.
  - **Deny signalling.** Cursor documents exit 2 as "equivalent to returning
    `permission: deny`". For plugin hooks that is false: a hook returning exit 2 with the
    reason on stderr was witnessed NOT blocking -- the command ran. The adapter now also
    emits Cursor's stdout response (`{"permission": "deny", "user_message",
    "agent_message"}`) for Cursor-shaped payloads only; Claude and Copilot still get
    exit 2 with an empty stdout, asserted by test.
  Witnessed blocking on a real Cursor install after both fixes, with a benign command in
  the same session still allowed.
- **A silent guard can no longer become a silent allow**: the PreToolUse adapter now
  guarantees a reason on stderr for every deny. Codex records exit 2 with an empty
  stderr as a FAILED hook ("did not write a blocking reason to stderr",
  `codex-rs/hooks/src/events/pre_tool_use.rs`) and lets the command run, so a guard that
  denied without explaining itself would have enforced nothing there while every other
  client showed a deny. Harmless elsewhere; load-bearing on Codex.
- The marketplace lockfile test now derives its expected tree set from `FORMATS` rather
  than an enumerated list -- the same under-coverage a hand-written list caused once
  before, where a newly added tree escaped the check while it still read as complete.

- **Bundled authoring skills use the same flat metadata**: the five shipped skills
  (chock-init, eval, optimize, policy-init, validate) carried the nested `chock:`
  object the packaged-policy fix removed — two metadata dialects in one project.
  Their frontmatter is now the same flat string map (lists comma-joined, booleans
  as "true"/"false"), and manifest ingestion decodes the typed fields; the derived
  manifests are proven identical. Old nested frontmatter still loads, so
  third-party skills are unaffected.
- **SKILL.md `metadata` spec fix**: the Agent Skills spec (which Agent Plugins 1.0
  defers to for SKILL.md) requires `metadata` to map string keys to string values;
  the packaged skills nested a `chock:` object there, which awesome-copilot's `vally`
  linter rejected ("Metadata values must be strings"). Now a flat map with dotted
  keys (`chock.artifact`, `chock.enforcement`, `chock.coverage_without_chock`) —
  same facts, spec-conformant shape. A parsed-not-substring test pins the constraint.
- **Posture-aware skill frontmatter**: a hook-carrying package's SKILL.md used to
  state `coverage_without_chock: advisory` next to the very hook that enforces —
  one package stating and refuting a claim at once. The frontmatter now swaps the
  advisory claim for the shipped hook's path (`chock.hooks`), the same substitution
  the hook emitters already made in plugin.json and the closing note.
- **`copilot` plugin format**: `chock plugin build --format copilot` emits the Agent
  Plugins 1.0 layout — root `plugin.json`, `skills/` — with the enforcing PreToolUse
  hook under `com.github.copilot/hooks/hooks.json`, the namespace directory VS Code
  documents for Agent Plugins hook bundles and non-Copilot clients must ignore. This
  is the shape spec-validating marketplaces (awesome-copilot) accept; the Claude
  layout, which Copilot also reads, keeps its manifest in `.claude-plugin/` and fails
  their intake. Hook command, adapter and guard are byte-identical to the Claude
  package's (asserted in tests): two formats, one enforcement system. The posture is
  scoped to this format's audience — generic Agent Plugins clients are required to
  ignore `com.github.copilot`, so the description names where the hook enforces
  (documented for VS Code agent mode) and that a namespace-ignoring client gets the
  advisory skill only. Hook-carrying packages replace the `coverage_without_chock`
  extension claim with the hook's location, and the dangling `manifest: manifest.yaml`
  pointer (a file this out-of-place format never ships) is dropped — each package
  carries only claims that are true of it. `--format all` now emits three trees.

## 0.3.0 — Native pre-tool-use for Copilot CLI and VS Code

- **`agent-hooks` enforcement surface**: `chock sync` now writes `.github/hooks/chock.json`,
  the native pre-tool-use hook read by **Copilot CLI and VS Code agent mode**. Both honour
  exit 2 as deny (witnessed blocking on both). The hook resolves its interpreter at run time
  — skipping the Windows Store `python3` alias stub that made hooks error — and finds the
  repo root with `git rev-parse`, so the committed file is portable with no baked path. One
  adapter now parses all three payload shapes (Claude, Cursor, Copilot/VS Code). Coverage is
  credited `enforced` for copilot/vscode only when the file is verifiably installed. Guards
  are bash-oriented, so on Windows PowerShell they catch bash-syntax commands but not
  PowerShell-native destructive syntax until a PowerShell guard ships (documented caveat).

## 0.2.0 — First release with an external contribution

MINOR: new features and adapters; compiled output for existing policies is unchanged
(golden-suite verified), but new surfaces exist.

- **Antigravity CLI adapter** — contributed by @alexsmolya, the project's first external
  contribution: `.agents/rules/chock.md` workspace rule, ambient/git-hook/CI surfaces
  (deliberately not pre-tool-use: no installer exists, so no claim is made).
- **Claude-format plugin emitter**: `chock plugin build --format claude|all --out-dir`
  renders each policy into Claude Code's plugin layout (read natively by Claude Code,
  Copilot CLI, VS Code and Grok Build), with the fail posture stated verbatim in every
  emitted description and per-format subtrees so no package has to lie for another
  client. Stale-output reconciliation, duplicate-id refusal.
- **`chock marketplace build`**: derives the marketplace index, a content-addressed
  `chock-market.lock` (sha256 per published plugin directory), and a generated
  `PLUGINS.md` catalog page from the built packages — never hand-listed, drift-checked.
- **Hook interpreter honesty**: the emitted hook command stays a single `python3`
  invocation -- a review of the proposed `python3 || python` fallback proved a chain
  can erase a deny verdict (a deny exit followed by a missing-interpreter exit reads
  as an error, and the first leg consumes stdin), so it was rejected with
  measurements. Instead every emitted description now states the per-client fail
  posture: fail-open clients allow silently without `python3` and a usable bash;
  fail-closed clients (VS Code) refuse matched commands; Windows needs the
  Microsoft Store `python3` alias disabled or Python installed.
- **Supply chain**: the Marketplace action no longer interpolates workflow inputs
  into shell (two HIGH template-injection alerts, fixed by env indirection); GitHub
  Releases are created by the runner's own `gh` CLI instead of a third-party action;
  the semgrep scanner installs hash-pinned via compiled requirements; Dependabot
  gets a 7-day cooldown.
- **CI pressure testing**: zizmor, actionlint, ShellCheck, and Semgrep (with custom
  rules encoding this project's own incidents) run as required checks; all three
  public repos are at zero open code-scanning alerts.
- **Fix**: `chock remove` refuses when a policy's manifest cannot be read — an
  unreadable manifest previously read as "not mandatory" and allowed deletion.
- **Fix**: `frontier_ingest` no longer prints and exits at import time; frontier
  validation shares one `STANDARDS_DIR` with ingestion.
- **Tests**: 755 (from 736); statement coverage 83%; new suites for the plugin
  emitter, marketplace, `chock remove`, and the frontier validation modes.


## 0.1.1 — Hardening and governance PATCH

Compiled output is byte-identical to 0.1.0 (golden-suite enforced); everything here is
validation, supply chain, documentation, and tests.

- **Fix**: policy-id validation now uses `fullmatch` — an id with a trailing newline
  was accepted by Python's `$`-before-newline matching. Found by the new
  property-based suite.
- **Supply chain**: every GitHub Action pinned to a commit SHA; least-privilege
  `permissions:` on all workflows; pip installs hash-pinned via compiled requirements;
  release artifacts now carry build provenance attestations; weekly coverage-guided
  fuzzing (atheris) of the id and selection parsers.
- **Governance docs**: GOVERNANCE.md (decision-making, roles, access continuity) and a
  public roadmap index; SECURITY.md gains advisory URL and response timelines.
- **Tests**: property-based suite for id validation and agent selection; unit suites
  for the lifecycle umbrellas and frontier ingestion (statement coverage 78% → 81%).
- **Marketplace**: the GitHub Action is listed as "Chock Governance Check" with branding.

## 0.1.0 — First public release

Everything below is the launch surface; `0.0.1a0` was a name-claiming pre-release, so this
is the first version with real contents.

- **Policies as code**: versioned policy manifests committed to the repo, compiled by
  `chock sync` to every enforcement surface each agent supports.
- **Enforcement surfaces**: pre-tool-use guards (Claude Code and Cursor), git hooks,
  a CI gate (`chock sync --ci` + commit-range mode), and ambient rules for
  instruction-file agents.
- **Coverage honesty**: per-agent, per-policy claims at three levels — `enforced`,
  `enforced-at-commit`, `advisory` — raised only when the installed mechanism is
  witnessed for that agent.
- **Arm-on-clone**: cloned repos re-arm through an ambient rule plus a consented
  SessionStart hook; git never clones hooks and Chock does not fight that boundary.
- **Catalog adoption**: `chock add <id>` installs hash-pinned policies from any
  catalog, public or private; every published policy ships with replayed evals.
- **Compliance frameworks built in**: OWASP Agentic Security Top-10, MITRE ATLAS,
  NIST AI RMF, EU AI Act — manifests claim framework coverage, `chock check` reports it.
- **Versioning contract**: PATCH releases never change compiled output (enforced by a
  golden-file suite); MINOR releases may.

## 0.0.1a0 — Name-claiming pre-release

Not a feature release. PyPI has no name-reservation mechanism — a project name is claimed only
by uploading a distribution — so this exists to claim `chock`, and to exercise the
release pipeline once on a disposable version before it matters.

Published as a pre-release rather than as `0.0.1` because PyPI versions are immutable: a
`0.0.1` uploaded now could never be replaced by the real one.

Contents are `0.0.1` as described below, plus Agent Plugins packaging. Treat it as early
access — the CLI surface, the manifest schema and the compiled output may all change before
`0.0.1`.

## 0.0.1 — Initial public baseline

First published baseline of the agent-neutral policy-engineering framework:

- Neutral policy spec with traced invariants (`spec/enforcement-matrix.md`), JSON schemas, and methodology.
- Meta-skills: `policy-init`, `validate`, `eval`, `optimize`, `chock-init` — all at lifecycle `review`, trust tier `community`.
- Deterministic tooling: validator, registry with script-integrity hashes, and dispatcher-based git hooks.
- Security posture: ambient-context integrity (SEC-1..7), deterministic-first execution (DET-1..4), effects/approval gating (EFF-1).
- Thin adapters for 13 agent surfaces with `AGENTS.md` as the single source of truth.
- The reference repo validates at 0 errors, 0 warnings, 0 infos under its own tooling.

Packaging and layout:

- Tooling ships as an installable `chock` package (`src/chock/`) with one
  CLI and activity-named subpackages: `validation/`, `registry/`, `hooks/`, `authoring/`.
- CLI subcommands: `validate`, `registry`, `install-hooks`, `check-matrix`.
- Taxonomy is agent-only: deliverables are skill, rule, hook, command, and subagent; no worker or headless orchestrator runtime.
- Every file in the repo respects the 300-line review budget, enforced by `tests/test_repo_standards.py`.
- Single owner handle `open-coder-ai` across provenance, reviews, and CODEOWNERS.

Pre-release iteration history (internal versions 0.2.x–0.6.x) is preserved in git log.
