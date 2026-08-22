# Chock changelog

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
- **Fix**: the emitted plugin hook command falls back from `python3` to `python` --
  on Windows, `python3` is routinely the Microsoft Store stub, and a client that
  treats a hook error as deny (VS Code) refused every shell command with an
  enforcing plugin installed.
- **Fix**: `chock remove` refuses when a policy's manifest cannot be read — an
  unreadable manifest previously read as "not mandatory" and allowed deletion.
- **Fix**: `frontier_ingest` no longer prints and exits at import time; frontier
  validation shares one `STANDARDS_DIR` with ingestion.
- **Tests**: 749 (from 736); statement coverage 83%; new suites for the plugin
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
