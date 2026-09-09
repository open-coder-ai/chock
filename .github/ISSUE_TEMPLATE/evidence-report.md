---
name: Evidence report
about: Report whether a compiled surface actually fired on the agent it was compiled for
labels: evidence
---

Chock compiles one policy to several surfaces (`git-hook`, `ci-gate`, `pre-tool-use`,
`agent-hooks`, `ambient-rule`, ...). A coverage level is only claimed when there is an
install *witness* for it -- someone watched the compiled artifact actually run in the
vendor's own client. Rows without one stay marked `witnessed: false` (see
[Enforcement Surfaces](https://github.com/open-coder-ai/chock/blob/main/docs/enforcement-surfaces.md)).
If you ran `chock sync` against a real agent, closing that gap is a couple of minutes.

**Policy** (id under `.agents/policies/`, e.g. `block-destructive-commands`):

**Agent and version** (exactly as the agent reports it, e.g. `cursor 3.17.8`):

**Surface compiled** (`pre-tool-use`, `agent-hooks`, `git-hook`, `ci-gate`, `ambient-rule`, ...):

**How you triggered it** (command run, or the action the guard should have caught):

**What actually happened** — did it block, ask, allow, or crash? Paste the raw output,
exit code, or the client's own denial dialog:

**Expected, per the docs above:**

**Platform** (OS, shell):

**Date observed:**

---

- [ ] I ran `chock sync` (or already had it installed) and this is what the real client did, not what the docs say it should do.
- [ ] I skimmed the pasted output and it contains nothing I would not post publicly (no prompts, file contents, or secrets).
