# Contributing to Chock

**First off — thank you.** 🎉 Chock gets better every time someone reports a confusing error message, fixes a typo, proposes a new guardrail, or challenges a design decision. You're in the right place.

## 💛 Every contribution counts — not just code

You do **not** need to write Python to make a real difference here:

- 📝 **Docs & examples** — clarify a confusing section, add a real-world policy example, fix a typo.
- 🐛 **Bug reports** — a good reproduction is worth its weight in gold. [Open an issue](https://github.com/open-coder-ai/chock/issues/new).
- 🎨 **Design & DX** — diagrams, a demo GIF, better CLI output, a clearer error message.
- 🛡️ **New policies — the contribution we want most.** Write a policy manifest for the
  guardrail your stack needs and send it to the catalog: [open a Policy Proposal
  issue](https://github.com/open-coder-ai/chock/issues/new?template=policy_proposal.md)
  to start one, or see [Anatomy of a good policy PR](#-anatomy-of-a-good-policy-pr) below.
- 💬 **Ideas & feedback** — start a [Discussion](https://github.com/open-coder-ai/chock/discussions). Telling us what's confusing *is* a contribution.

## 🛠️ Development Setup

```bash
# 1. Fork the repo on GitHub, then clone YOUR fork
git clone https://github.com/<your-username>/chock.git
cd chock

# 2. Install editable with dev dependencies (Python 3.11+).
# A non-editable install can produce stale-schema `validate` errors after you
# change files under validation/schemas/, so always use -e here.
pip install -e '.[dev]'

# 3. Verify your environment — everything below should pass
pytest -q                  # test suite (bash + PowerShell guards, both OSes)
ruff check .               # lint
ruff format --check .      # format
chock check    # artifacts conform to the spec
chock check --only matrix  # enforcement-matrix traceability
chock registry scan # registry stays fresh (CI diffs this)
```

If those are green, you're ready to build. 🚀

## 🏷️ Releasing

Version is single-sourced in `pyproject.toml`.

1. Bump `version` in `pyproject.toml`.
2. Update the top `## X.Y.Z` entry in `CHANGELOG.md`.
3. Commit, then `git tag vX.Y.Z && git push origin vX.Y.Z`.
4. The `release` workflow builds the wheel/sdist, publishes to PyPI via Trusted Publishing,
   builds one-file binaries for Ubuntu, macOS, and Windows, and creates a GitHub Release with
   the binaries and `checksums.txt`.

The release workflow fails the guard step if the tag does not match `pyproject.toml`.

### The emitter-stability promise

Adopters commit compiled artifacts, so every engine bump makes their drift checks compare
those bytes against what the new engine produces. Versioning is therefore a promise about
regeneration:

- **Patch release** — emitter output is byte-identical. A patch bump never requires
  `chock sync`. Enforced by `tests/test_emitter_stability.py` against a committed golden
  tree: if your change breaks it, your change is not a patch.
- **Minor release** — emitter output may change. Regenerate the goldens in the same PR
  (`CHOCK_REGEN_GOLDENS=1 pytest tests/test_emitter_stability.py`) so reviewers see
  exactly what every adopter's next `chock sync` will rewrite, and say so in the
  changelog. Adopters bump, run `chock sync`, commit the diff.
- **Major release** — anything an adopter must *do* beyond `chock sync` (config or
  layout migration, removed commands).

> **Authoring a policy?** Policies live in `.agents/policies/<id>/`. Scaffold one with `chock new policy <id>` — you'll get the manifest, gate, and eval stubs to fill in. See the [Authoring Policies guide](docs/authoring-policies.md).

## 🌱 Branch & Pull Request Workflow

We keep `main` clean and protected — in fact, **Chock enforces this on itself** (you literally cannot commit straight to `main`; that's the `protect-main-branch` guard dogfooding). So always work on a branch.

**1. Branch naming** — `type/short-description`:

| Prefix | Use for |
| :--- | :--- |
| `feat/` | New feature or policy (`feat/scan-secrets-entropy`) |
| `fix/` | Bug fix (`fix/windows-hash-order`) |
| `docs/` | Documentation only (`docs/quickstart-clarity`) |
| `test/` / `chore/` | Tests or tooling |

**2. Commit messages** — [Conventional Commits](https://www.conventionalcommits.org):

```text
feat(policies): add entropy-based detection to scan-secrets
fix(registry): sort script-hash keys for cross-OS determinism
docs(readme): clarify the 2-minute quick start
```

**3. Open the PR** against `main`, describe **what** changed and **why**, and make sure **CI is green** (`validate`, `ruff`, `pytest`, `check-matrix` run on Ubuntu + Windows). One reviewer approval merges it; we aim to give first feedback within a few days.

## ✍️ Sign your commits (DCO)

This project uses the [Developer Certificate of Origin](https://developercertificate.org/) (DCO)
instead of a CLA: no paperwork, no copyright assignment — a one-line trailer on each commit
certifying you have the right to contribute the change under the project's license
(Apache-2.0).

Add the trailer with the `-s` flag:

```bash
git commit -s -m "feat(policies): add entropy-based detection to scan-secrets"
```

which appends:

```text
Signed-off-by: Your Name <your.email@example.com>
```

CI checks every commit on a PR for the trailer. Forgot one? Amend and force-push your branch:

```bash
git commit --amend -s --no-edit && git push --force-with-lease
```

(or for several commits, `git rebase --signoff main`). The name and email must be real enough
to stand behind — the sign-off is you certifying the DCO, not a formality.

**Automate it** so you never discover the requirement via a CI rejection: install
[pre-commit](https://pre-commit.com) once, then enable the `commit-msg` hook this repo
ships (`.pre-commit-config.yaml`) —

```bash
pip install pre-commit
pre-commit install --hook-type commit-msg
```

— and every commit gets the `Signed-off-by` trailer automatically from your `git config
user.name` / `user.email`, whether or not you remembered `-s`.

## 🤖 Agent-authored code

**Use an agent if you want to. Every change still gets read by a human before it merges,
including ours.**

Worth saying out loud rather than leaving to be inferred. Much of this repository was written
with Claude Code — the `Co-Authored-By` trailers are in the log and are not going to be quietly
dropped. A project that builds guardrails for AI coding agents and is coy about having used one
has a credibility problem; a project that uses one without review has a worse one.

The rule is symmetric, and it is about the review rather than the author:

- **Disclose it.** Keep the `Co-Authored-By` trailer your tool adds. Nobody will think less of
  the PR for it.
- **A human reads the whole diff before merge.** Not the summary, and not just the changed hunks
  of a guard script. This applies to maintainer PRs too — there is no fast path for ours.
- **You are the author.** "The agent wrote it" is not an explanation for a change you cannot
  defend in review. If you could not answer a question about a line, take that line out.

Two places where review will be slower on purpose:

- **`.agents/policies/`, and anything that compiles into a hook or guard.** This becomes
  executable content in other people's repositories.
- **`coverage_level`, `INSTALLED_SURFACES`, and the validation checks.** These decide what the
  tool *claims*. An agent optimising for a green suite will usually find the claim easier to
  change than the mechanism, and that is the one edit this project cannot afford to wave
  through.

This is the policy for at least the project's first months. If it changes, it changes here, with
a reason.

## 📐 Project conventions (the house style)

These keep the framework lean, deterministic, and reviewable. New contributions should follow them:

- **Evals before descriptions** — draft `evals/suite.yaml` before finalizing a skill description or rule text.
- **Budgets** — `SKILL.md` ≤ 150 lines · description ≤ 500 chars · reference files ≤ 300 lines · ambient rules ≤ 2 lines.
- **300-line file budget** — no reviewable file (source, docs, spec, or data) exceeds 300 lines; split by activity instead. Enforced by `tests/test_repo_standards.py`.
- **Deterministic-first** — if an operation can be a committed script, it must be one. Reserve LLM steps for judgment that can't be scripted.
- **The five-place rule** — every new requirement lands in all five places, or it will drift:
  `spec invariant → schema field → validator/runtime check → generation template → CI`.

## 🧪 Anatomy of a good policy PR

When you add or change a policy, include all of these:

1. **Manifest** (`manifest.yaml`) — id, `artifact` type, `enforcement`, `effects`, and a clear `description`.
2. **Implementation** (for hooks) — declarative policies ship no scripts: the `hook.gate` block in `manifest.yaml` is the implementation. Scripts under `implementations/` exist only for guards that the declarative gate DSL cannot express.
3. **Evals** (`evals/suite.yaml`) — at least one `trigger`, one `negative_trigger`, one `behavior`, and one adversarial case. See the [Evals guide](docs/evals.md).
4. **Housekeeping** — bump the manifest `version` + changelog entry, regenerate derived artifacts (`chock registry scan`), and keep the spec/matrix in the same PR as the behavior.
5. **Green checks** — `chock check` and `pytest` pass clean. The reference repo must validate under its own tooling.

## 🔄 Artifact lifecycle

Artifacts follow `draft → review → production → deprecated` (spec §8). Promotion to `review` requires green validation and a recorded `reviewed_by`; promotion to `production` requires PR approval. Trust-tier upgrades happen only at review time.

## 🏷️ Labels — where to start

Browse issues by label to find your entry point:

- 🟢 [`good first issue`](https://github.com/open-coder-ai/chock/labels/good%20first%20issue) — small, well-scoped, and mentored. **Start here.**
- 🙌 [`help wanted`](https://github.com/open-coder-ai/chock/labels/help%20wanted) — we'd love a hand; slightly bigger than a first issue.
- 🐛 `bug` — confirmed defects.
- 📝 `documentation` — no code required.
- 💡 `enhancement` / `policy-request` — new capabilities and guardrails.

Comment on an issue to claim it — we'll assign it to you so no one double-works.

## 📜 Code of Conduct

Be kind, be curious, assume good faith. We're all here to make AI-assisted development safer. Harassment of any kind isn't tolerated.

The full text is in [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) (Contributor Covenant 2.1), including how to report an incident.

**Welcome aboard.** ⚓
