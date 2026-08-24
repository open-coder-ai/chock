# Adopting Chock

Two adoption postures, one mechanism:

- **A team protecting its own repos** — fork-as-template, below: your engineers and your
  agents, your policies merge-safe against upstream.
- **An open-source maintainer protecting a public repo** — you do not choose which agents
  contributors bring, but policies are committed content, so your rules travel with every
  clone and fork: ambient rules reach any agent with zero setup, the repo
  [re-arms itself](#arming-a-fresh-clone) for hooks, and the CI gate holds on every fork
  PR regardless of what the contributor runs. Start with `chock init` + `chock add` on the
  repo itself; the template workflow below is optional.

The intended workflow for a team is to **fork the framework repo once** and use it as a template for every consumer repo. This keeps your customizations merge-safe when the upstream framework evolves.

## Start from the template

1. Fork `https://github.com/open-coder-ai/chock` into your org.
2. Clone the fork and use it for a new repo, or `git remote add template <your-fork>` in an existing repo and merge.
3. Run `chock init .` in the consumer repo to scaffold the wiring. It installs no
   policies; copy the ones you want from a catalog into `.agents/policies/<id>/` and run
   `chock sync --repo .`.
4. Commit the result — including `.chock/compiled/` and `.chock/bin/gate.py`. Note that the
   hooks themselves live in `.git/hooks/`, which git does **not** clone: a fresh clone enforces
   nothing until someone runs `chock sync --repo .` in it, which reinstalls the hooks from the
   committed artifacts.

## Stay up to date

Add the upstream framework repo and merge updates into your fork:

```bash
git remote add upstream https://github.com/open-coder-ai/chock
git fetch upstream
git merge upstream/main
```

Resolve any conflicts in framework files by keeping the upstream version and moving your changes into `.chock/config.yaml` or your own policies.

## Golden rule: customize in these places only

| Want to change | Do this | Never edit |
| :--- | :--- | :--- |
| Protected branch names | `.chock/config.yaml` → `defaults.protected_branches` | the installed policy manifest |
| Disable a policy | `.chock/config.yaml` → `policies.disabled` | deleting the policy folder |
| Add a team policy | `chock new policy <id>` | editing an unrelated policy |
| Add a skill or adapter | `chock new` or `install-skills` | generated adapter files |

Customizing only in your own policies and config means `git merge upstream/main` stays clean.

## Runtime requirement

Enforcement at commit/push time needs only **a Python 3.11+ interpreter on PATH** (`python3`, `python`, or `py` — the shim probes each for one that can import `tomllib`). The compiled git hook shims call:

```bash
python3 .chock/bin/gate.py run --gate .chock/compiled/<id>/git-hook/gate.json --event pre-commit
```

On Windows this may be `python` or `py`; the generated shim probes for a working interpreter automatically. No `pip install chock` is required on the machine enforcing the gate; the runner is vendored into the repo.

## Arming a fresh clone

Git never clones `.git/hooks/` — by design, because "cloning a repo executes the repo's
code" would be remote code execution. Chock does not fight that boundary; it shrinks the
gap with three mechanisms, each consented where consent is required:

1. **The ambient arm rule (every agent, zero setup).** The managed pointer block in
   `AGENTS.md` — read by all fourteen adapters — tells the agent:
   `fresh_clone: git never clones hooks -> run(chock sync --repo .) before first commit`.
   A contributor's coding agent arms the hooks before it can trip them.
2. **The SessionStart arm hook (Claude Code, automatic).** `chock sync` wires a
   `SessionStart` entry into the committed `.claude/settings.json` that runs the vendored
   `.chock/bin/sessionstart.py` when a session opens — consented through Claude Code's
   workspace-trust prompt, the same gate PreToolUse passes through. If the hooks are
   already armed it stays silent; if `chock` is installed it runs `chock sync` itself; if
   not, it prints the exact command into the session context so the agent runs it.
3. **Bootstrap piggyback (humans, and every other entry path).** Put `chock sync --repo .`
   wherever contributors already run setup:

   ```jsonc
   // .devcontainer/devcontainer.json — arms automatically in Codespaces
   { "postCreateCommand": "pip install chock && chock sync --repo ." }
   ```

   ```jsonc
   // package.json — arms on npm install
   { "scripts": { "prepare": "chock sync --repo . || true" } }
   ```

   ```make
   setup:  ## make setup
	pip install chock && chock sync --repo .
   ```

None of these is the guarantee. The guarantee is the **CI gate** (`chock sync --ci`),
which runs on the maintainer's side for every pull request and does not depend on the
contributor arming anything.

## How to verify a fresh clone enforces

After `git clone` in a fresh directory, the committed artifacts are present but the git hooks
are not — `.git/hooks/` is never cloned, so the repo enforces **nothing** until the hooks are
reinstalled:

1. Run `chock sync --repo .` to install the hooks from the committed artifacts.
2. `ls .chock/bin/gate.py` should exist.
3. `ls .chock/compiled/scan-secrets/git-hook/gate.json` should exist.
4. Commit a file containing a credential. `scan-secrets` should block it and print the policy message.

If your consumer `.gitignore` contains a broad `.chock/` rule, add un-ignore lines so the committed artifacts stay tracked:

```gitignore
!.chock/bin/
!.chock/bin/**
!.chock/compiled/
!.chock/compiled/**
```
