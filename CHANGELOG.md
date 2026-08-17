# Chock changelog

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
