# CLI Reference

One entry point, two kinds of command:

```bash
chock <command> [args]
```

**Everyday** commands are the adopter surface — the same verbs the Python toolchain
already taught you (`uv init/add/sync`, `poetry check`, `git status`). **Authoring**
commands serve policy authors and catalog maintainers. Run `chock --help` for the live
list. All commands are deterministic — no AI agent or network required (except `add`,
which fetches from the catalog you point it at).

---

## Everyday

### `init` — onboard a repository

```bash
chock init [repo] [--agents claude cursor copilot] [--agent-agnostic] [--skip-hooks] [--force]
```

Scaffolds a consumer repo — **wiring only, no policies**: creates `.chock/` (config +
`chock.lock`) and an empty `.agents/policies/`, writes agent wrapper files, installs the
git hook dispatchers, and runs a validation self-check. Add policies afterwards with
`chock add` (or by copying a policy folder in and running `chock sync`). **Idempotent** —
safe to re-run; it overwrites derived files but never your own policies.

- `--agents` — space-separated target agents (default: `claude copilot gemini` — the agents that
  can't read `AGENTS.md` natively).
- `--agent-agnostic` — generate wrappers for all supported agents.
- `--skip-hooks` — skip git hook installation.
- `--force` — overwrite scaffolded files that have local edits (destructive).

A bare re-run keeps the `supported_agents` already recorded in `.chock/config.yaml` and
preserves any scaffolded file you have edited (reported as `[KEPT]`); `--force` overwrites them.

### `add` — install a policy or skill from a catalog

```bash
chock add <id> [--repo .] [--from URL_OR_PATH] [--ref BRANCH_OR_TAG]
               [--verify-sha SHA256] [--force] [--skip-compile]
```

Fetches one artifact from a catalog, copies it into `.agents/policies/<id>` (or
`.agents/skills/<id>`), and compiles it. `--from` defaults to the public catalog and also accepts a
local path, which is what CI and offline installs use.

| Flag | What it does |
| :--- | :--- |
| `--ref` | Pin the fetch to a branch or tag. Without it, `add` resolves the catalog's **default branch**. |
| `--verify-sha` | Refuse to install unless the fetched artifact hashes to this value. Checked *before* anything is written. |
| `--force` | Replace an artifact that is already installed. Refused by default — installed content is yours. |
| `--skip-compile` | Copy only; run `chock sync` yourself afterwards. |

`add` prints the resolved commit and the content hash, and records `source`, `source_ref` and
`source_commit` in `chock.lock`.

> **A catalog policy can contain guard scripts that run on every commit.** `add` installs executable
> content over `git clone`, with no signature verification — see the catalog trust model in
> [SECURITY.md](../SECURITY.md). Pin with `--ref` and check the hash with `--verify-sha` when the
> catalog is not one you control.

### `remove` — uninstall a policy

```bash
chock remove <policy-id> [--repo .]
```

The inverse of `add`: deletes `.agents/policies/<id>` and runs `sync` so the compiled tree,
hooks, index, registry, and lockfile all stop describing it. Refuses (exit 2) for policies
marked `mandatory: true`. To keep a policy installed but inert, use `disable` instead.

### `sync` — make the repo match its policies

```bash
chock sync [--repo .] [--agents claude cursor copilot] [--skip-hooks] [--check]
chock sync --ci       # also install the GitHub Actions CI-gate workflow
chock sync --skills   # also install the bundled authoring skills
```

The one "make it so" verb (`uv sync` semantics): recompiles every enabled policy from
`.chock/config.yaml` into `.chock/compiled/`, reinstalls the git-hook dispatchers and
policy wrappers, regenerates `INDEX.md` and the `AGENTS.md` pointer, refreshes the
registry, and rewrites `chock.lock`. Run it after editing a policy, toggling config by
hand, or bumping the engine version. A failed recompile never removes the existing
compiled tree — the build is staged and swapped in only on success — and a
lockfile-write failure fails the command. An adopter-edited dispatcher is backed up to
`<event>.chock-backup` before being regenerated; custom steps belong in `<event>.d/`.

- `--check` — write nothing; exit non-zero listing every compiled artifact that no longer
  matches its manifest. This is the CI drift gate.
- `--ci` — additionally write the GitHub Actions workflow that runs every compiled
  `ci-gate` on pull requests. Idempotent; refuses to overwrite a workflow it did not write.
  Until this runs, `ci-gate` output is compiled but not enforced.
- `--skills` — additionally refresh the bundled authoring skills in `.agents/skills/`.
- `--skip-hooks` — compile and refresh bookkeeping without touching `.git/hooks`.

### `check` — is this repo sound?

```bash
chock check [--repo .] [--only validate,verify,evals,matrix,index] [--mode MODE] [--event EVENT]
```

Runs every truth check, read-only — `check` never regenerates what it measures (that is
`sync`'s job):

| Target | What it proves |
| :--- | :--- |
| `validate` | Artifacts conform to the spec: schemas, budgets, security baseline, determinism, drift. |
| `verify` | Installed packs match `chock.lock` — both source and compiled-artifact hashes. |
| `evals` | Every policy's eval suite passes under deterministic replay. |
| `matrix` | Spec invariants are traceable in the enforcement matrix. Framework-repo homework: auto-skipped (with a note) in repos that have no `spec/enforcement-matrix.md`. |
| `index` | `INDEX.md` and the `AGENTS.md` pointer are fresh. |

- `--only` — comma-separated subset, e.g. `--only validate,verify`.
- `--mode` — frontier validation profile (e.g. `frontier-claude`), passed to `validate`.
- `--event` — hook event context (e.g. `commit`), passed to `validate`; softens
  pre-existing-drift findings at commit time.

### `status` — what is installed, and what happened

```bash
chock status [--repo .] [--only policies,registry,log]
```

Read-only. Default prints the policy table: every installed policy, its resolved state
(`enabled`, `overridden`, `disabled`), coverage level, and whether it is `mandatory`.
`--only registry` lists the artifact registry; `--only log` reports recorded gate
outcomes — including which policies have never fired.

### `enable` / `disable` — policy toggles

```bash
chock enable  <policy-id> [--repo .]
chock disable <policy-id> [--repo .]
```

`disable` adds a policy to `policies.disabled` in `.chock/config.yaml`, recompiles the
enabled policies, and removes its git-hook wiring. `enable` does the reverse. Both are
config overlays — the policy files stay untouched (unlike `remove`). `disable` refuses
with exit 2 if the policy is `mandatory: true`. Both reject unknown ids.

---

## Authoring

### `new` — scaffold an artifact skeleton

```bash
chock new {policy|skill|subagent} <id> [--root .]
```

Creates a valid, empty artifact folder (`manifest.yaml` with a `hook.gate` block,
implementation stub, `evals/suite.yaml`) ready to fill in — by hand or with the
`policy-init` skill in your agent.

### `compile` — low-level single-policy compile

```bash
chock compile <policy-id> [--repo .] [--targets SURFACE ...] [--agents AGENT ...] [--policy-dir DIR] [--output-root DIR]
```

Compiles one policy into the surfaces each target agent supports (git hook, CI gate,
Claude PreToolUse / managed-settings, `AGENTS.md` rule) and updates the per-agent
coverage report. `--agents` takes the same comma- or space-separated names as `init`
and `sync`, defaults to the repo's `supported_agents`, and rejects unknown names.
`sync` runs this for every enabled policy; reach for `compile` directly only when
iterating on a single policy's emitted output.

### `install-skills` — refresh the bundled authoring skills

```bash
chock install-skills [repo] [--skills policy-init optimize ...] [--check]
```

Copies the framework's authoring skills (`policy-init`, `validate`, `eval`, `optimize`)
into the canonical `.agents/skills/` directory — one copy, not one per agent. `--check`
reports drift without writing (CI runs this form).

### `registry` — scan / list / resolve the artifact index

```bash
chock registry scan       # rebuild .chock/registry.json
chock registry list       # list artifacts
chock registry get <id>   # metadata for an id
chock registry resolve <id>
```

`scan` recomputes the registry, including a `sha256` of every deterministic script. CI
diffs the result to catch a stale registry. See [Registry & Lockfile](registry-and-lockfile.md).

### `plugin build` — package policies as installable plugins

```bash
chock plugin build [--repo .] [--policies-dir base] [--format agent-plugins|claude|all] [--out-dir DIST] [--check]
```

Renders each policy as a plugin. The default `agent-plugins` format writes an
[Agent Plugins 1.0.0](https://agent-plugins.org) package into each policy folder —
additive, `manifest.yaml` stays the source of truth, and a packaged policy is `advisory`
wherever it is read: v1 defines no enforcement semantics, so packaging changes no value in
`coverage.json`.

`--format claude` emits Claude Code's plugin layout (`.claude-plugin/plugin.json`,
`hooks/`, `skills/`, `scripts/`), read natively by Claude Code, Copilot CLI, VS Code, and
Grok Build. A guard policy's plugin carries the guard and the stdlib-only PreToolUse
adapter and is session-enforced where the host honours the hook — failing **open** when
`python3` is absent, a posture each emitted description states verbatim. This format
requires `--out-dir` (plugins land in `<out-dir>/plugins/<id>/`); in-place output is
refused so a policy folder can never be mistaken for a published plugin. `--policies-dir`
packages a published directory (a catalog needs this); `--check` reports stale output
without writing.

### `marketplace build` — index a built plugin tree

```bash
chock marketplace build [--dist .] [--name chock] [--check]
```

Scans `<dist>/plugins/*/.claude-plugin/plugin.json` and writes the marketplace index to
`.claude-plugin/marketplace.json` and `.github/plugin/marketplace.json` (byte-identical
copies — the second is the path Copilot CLI reads). Entries are derived from the built
manifests, never hand-listed. An empty tree exits 2 rather than writing an index that
delists everything; `--check` reports drift without writing.

### `gateway run` -- the MCP gateway proxy

`chock gateway run --repo . -- <cmd>` wraps one downstream MCP server, refusing matching `tools/call` requests; fails closed (no proxy, no MCP).

### `review` — record and check what a review rests on

```bash
chock review emit   [--repo .] [--base origin/main] [--checks ...] [--kind agent|human] [--by NAME]
chock review verify [--repo .] [--base origin/main] <evidence.json>
```

`emit` runs every check in the repository's registry and writes evidence to
`.chock/evidence/<diff>.json`. `verify` re-derives each `verified` claim and exits
non-zero if any disagrees. Attested (human-judged) claims are printed under **NOT
verified** with their stated basis. The recorded `command` is never executed — the
verifier resolves checks through the registry, because evidence is contributor-authored.
Full format: [Reviewer Evidence](reviewer-evidence.md).

### `compliance report` — compliance coverage

```bash
chock compliance report [--repo .] [--framework owasp_asi] [--json]
```

Lists the framework controls and which installed policies claim to cover them. Each
control's state is `covered`, `partial`, or `uncovered` (per-claim `coverage` on a policy
is `partial` or `full`). The command fails closed with exit 2 on a missing `--repo`, an
unknown framework nothing claims, or an unknown subcommand. In a repo that has been
synced, a claim also requires the policy's compiled output to exist — a declared control
whose compiled mechanism was deleted is not counted.

Builtin frameworks (one per data file in `src/chock/authoring/data/`, each enumerated
from its publisher's primary source): `owasp_asi` (ASI01–10), `mitre_atlas` (170
techniques, from the official machine-readable dataset), `nist_ai_rmf` (the 72 AI RMF 1.0
subcategories), `eu_ai_act` (a curated set of technical-obligation articles). A policy
claims controls in its manifest's `compliance:` block, keyed by framework name — unknown
framework names still validate, so private frameworks work with `--json` and your own
control list.

## Pre-launch aliases

The pre-consolidation names (`validate`, `recompile`, `install-hooks`, `install-ci`, `refresh`,
`verify`, `eval`, `check-matrix`, `policies`, `gate-log`) still dispatch, hidden from `--help`; use the verbs above.

## Typical workflows

**Onboard and prove enforcement**

```bash
chock init .
chock add protect-main-branch
git checkout main && git commit -m x   # blocked by protect-main-branch
```

**Author, validate, compile a new guard**

```bash
chock new policy block-console-log
# …edit manifest.yaml (hook.gate) + evals…
chock check
chock compile block-console-log
```

**CI pipeline (see `.github/workflows/ci.yml`)**

```bash
ruff check . && ruff format --check .
chock check
chock sync --repo . --check
chock registry scan   # then diff to detect drift
pytest -q
```
