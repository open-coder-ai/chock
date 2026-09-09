# Why

Your team runs five AI coding agents — and if your repo is open source, contributors
bring agents you never chose. Each has its own config file and its own idea of "the
rules." You write *"don't force-push to main"* into a `CLAUDE.md`, a
`.cursorrules` and a `copilot-instructions.md` — and an agent does it anyway, because
**prose is a suggestion, not a control**. Chock is the control: author a policy once, and
a compiler emits the strongest enforcement each agent actually supports, plus a coverage
report that tells you — honestly — where a guarantee holds and where it is only advice.

*Chock (rhymes with "block"): the wedge set against a wheel so it cannot roll until
someone deliberately removes it.*

## For open-source maintainers

AI broke the oldest balance in open source: contribution volume now scales with compute,
while review capacity still scales with maintainer hours. A contributor with an agent can
open ten large PRs in a weekend; you are still one human reading diffs. And you get no say
in which agent they bring — Claude Code today, Cursor tomorrow, something new next month.

What you do control is the repo itself, and Chock policies are **committed content**, so
your rules travel with every clone and fork — the maintainer governs the contributor's
*agent*, not just the contributor:

- **Every contributor's agent reads your rules with zero setup.** The compiled `AGENTS.md`
  and per-agent adapter files are in the tree; agents pick them up ambiently the moment
  the repo is cloned.
- **The repo re-arms itself.** Git never clones hooks, so Chock has the agent close the
  gap: an ambient rule tells every agent to run `chock sync --repo .` before its first
  commit, and for Claude Code a committed SessionStart hook arms the git hooks
  automatically when a session opens — consented through the workspace-trust prompt.
  The blocked commit happens on the contributor's machine, before the pull request,
  instead of in your review queue. [How arming works](adopting.md#arming-a-fresh-clone).
- **The CI gate is yours and depends on nothing the contributor does.** `chock sync --ci`
  wires a commit-range gate into your pipeline, so a policy skipped or bypassed locally is
  still enforced on the PR.

Today the alternative is reviewing agent-written contributions with another agent, or by
hand — triage after the code already exists. With Chock the rules reach the contributor's
agent *before the code is written*, and what still arrives has already passed your gates:
**review the policy once, instead of every PR.**
