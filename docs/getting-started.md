# Getting Started

This guide takes you from zero to an enforced, validating repo — and your first custom policy — in about ten minutes. It applies the same way to a team codebase and to a public open-source repo; for the maintainer-specific angle (contributors' agents, forks, arming on clone) see [Adopting Chock](adopting.md).

## Prerequisites

- **Python 3.11+** (for pip/pipx/source installs)
- **git**
- A shell with **bash** available for git hooks (Linux/macOS have it; on Windows, Git for Windows provides it)

## 1. Install

Pick one of the install methods below:

| Method | Command |
| :--- | :--- |
| pipx (recommended) | `pipx install chock` |
| Standalone binary | planned — not published yet |
| Homebrew | planned — not published yet |
| Scoop | planned — not published yet |
| Source | `git clone … && pip install -e .` |

> **Git hooks need bash *and* Python at runtime.** The pre-commit / pre-merge-commit / pre-push
> guards are compiled `gate.json` files executed by the vendored Python runner, so the machine
> making commits needs bash plus a Python 3.11+ interpreter on `PATH` — whichever way the CLI
> was installed.

After install:

```bash
chock --help
```

The command list it prints is generated from the code, never hand-maintained, so it is always
complete.

> **If `chock` isn't found**, your Python scripts directory isn't on `PATH`. Use
> `python -m chock …` instead — it works regardless of PATH, and every command below accepts it.

## 2. Onboard a repository

From inside the repo you want to protect:

```bash
cd /path/to/your/project
chock init .
```

`init` is fully deterministic — no AI agent required. It:

- creates `.chock/` (config + lockfile + `dependency-allowlist.txt`) and an empty `.agents/policies/`,
- writes `AGENTS.md`, a `.gitattributes` pinning generated scripts to LF, the agent wrapper files
  (`.claude/CLAUDE.md`, `.cursor/rules/…`, `.github/copilot-instructions.md`, …), and the
  guardrail pairs `.agents/policies/{AGENTS.md,CLAUDE.md}` and `.agents/skills/{AGENTS.md,CLAUDE.md}`,
- installs the four authoring skills (`policy-init`, `validate`, `eval`, `optimize`) into
  `.agents/skills/`, and
- installs the git hook dispatchers.

It installs **no policies**, and tells you so — a freshly initialised repo enforces nothing yet.
Policies are content, not framework, and you choose which to adopt.

By default it targets the agents that can't read `AGENTS.md` natively: `claude`, `copilot`, and
`gemini`. Pass `--agents` to change that:

```bash
chock init . --agents claude cursor copilot codex gemini aider
```

Re-running `init` is safe: files you have edited are kept, and it says which it left alone. Use
`--force` when you genuinely want them overwritten.

## 3. Install a policy

```bash
chock add protect-main-branch
chock sync --repo .
```

`add` fetches from the base catalog
([`chock-catalog`](https://github.com/open-coder-ai/chock-catalog)), copies the
artifact in, and compiles it. Point it elsewhere with `--from <url-or-path>`; transport is
`git clone`, so a private catalog works with the credentials you already have.

Once installed, the policy is **yours** — edit it freely. `add` refuses to replace an
installed artifact unless you pass `--force`.

## 4. See enforcement in action

`protect-main-branch` blocks direct commits to protected branches:

```bash
git checkout main
echo "oops" > hotfix.txt && git add hotfix.txt
git commit -m "straight to main"
# ❌ Direct commits/pushes to a protected branch (main|master) are blocked.
#    Create a feature branch and open a pull request.
#      - main

git checkout -b feature/x
git commit -m "on a feature branch"   # ✅ allowed
```

The same rule is also compiled into your agents' native controls, so Claude Code (for example)
is stopped *before* it runs the command — not just at commit time.

## 5. Author your first policy

Scaffold a new guard:

```bash
chock new policy block-console-log
```

This creates `.agents/policies/block-console-log/` with a manifest, a gate, an implementation stub,
and an eval suite. Edit the manifest:

```yaml
# .agents/policies/block-console-log/manifest.yaml
id: block-console-log
name: "No console.log in committed code"
artifact: hook
enforcement: block
effects: [read_only]
description: >
  Block staged JS/TS changes that add console.log.
hook:
  gate:
    kind: content_regex
    "on": [commit]
    action: block
    message: "console.log added -- remove debug output before committing."
    params:
      content_pattern: "console\\.log"
```

The `hook.gate` block is what actually enforces: a blocking hook with no gate fails validation.

Then refresh the index and validate:

```bash
chock sync              # update .agents/policies/INDEX.md
chock check           # conforms to the spec?
chock compile block-console-log   # emit surfaces + coverage report
```

You can now read `.agents/policies/INDEX.md` to see the new `block-console-log` rule listed
alongside any policies you installed. `enable` and `disable` recompile as part of their run;
`new` and `install-skills` only refresh the registry and index — they do not run `sync`. After
editing a gate, run `chock sync --repo .` to recompile.

See [Authoring Policies](authoring-policies.md) for writing the guard logic and evals.

## 6. Keep it reproducible

`init` writes a `chock.lock` with an empty packs list; `sync` and `add` populate it, pinning
each installed pack by content hash. Verify a repo
hasn't drifted at any time:

```bash
chock check --only verify        # "all packs match lockfile"
```

## Where to go next

- [Core Concepts](concepts.md) — the vocabulary in one page
- [CLI Reference](cli-reference.md) — every command in depth
- [Enforcement Surfaces](enforcement-surfaces.md) — what "enforced" means per agent
- [Policies](baseline-policies.md) — what the base catalog offers and how to customise it
