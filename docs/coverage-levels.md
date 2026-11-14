# Coverage Levels

The vocabulary every claim on [Enforcement Surfaces](enforcement-surfaces.md) is worded in:
what a grade in `.chock/coverage.json` means, how strong each word is relative to the others,
and what kind of evidence may back it. Held apart from that page because choosing a surface
and reading a grade are different questions; the basis-cap table at the end is the honesty
anchor every claim on either page is checked against.

## The levels

For each policy × agent, the compiler records one of eight levels in `.chock/coverage.json`.
The first four come from the **in-agent ladder** — agentseam's own honest, per-agent vocabulary
(`agentseam.matrix.enforcement_level`, owner decision #9) for an installed, in-agent pre-execution
control, plus one level of chock's own — because a hook that fails OPEN on a crash is a materially
weaker promise than one that fails closed, and an adopter deciding on trust needs to see the difference.

| Level | Meaning |
| :--- | :--- |
| **`enforced`** | An installed, hard, pre-execution in-agent control that fails CLOSED — a crashed hook still blocks. |
| **`enforceable`** | Installed and blocks, and CAN be told to fail closed, but does not by default — what an adopter may claim depends on how the hook was installed. |
| **`fail-to-ask`** | Installed and blocks, and when the control itself cannot decide the action does **not** proceed unattended — it is put to a human. The host may still fail open if the hook never runs at all, which is why this sits below `enforceable`. **Chock does not earn this level today**; see below. |
| **`best-effort`** | Installed and blocks, but fails OPEN — a crashed hook silently allows. claude_code's PreToolUse is this tier today. |
| **`enforced-at-commit`** | The policy emitted a git-hook (installed automatically) or a CI gate whose workflow `install-ci` has actually written — hard at commit time or over the PR's commit range, advisory in-agent. Chock's own commit-time mechanism, outside agentseam's per-agent-hook model. |
| **`advisory`** | Only the ambient rule applies — compiled prose the agent is asked to follow. Also outside agentseam's model: an ambient rule is not a lifecycle hook of any kind. |
| **`none`** | Nothing the policy emitted reaches this agent. |
| **`disabled`** | The policy is listed in `policies.disabled` and produces no artifacts or hooks. |

## The in-agent ladder is ordered, and the order is the point

The four in-agent levels plus `none` form a strength ladder, weakest first — the order
`compile.levels.level_rank` returns, and the order this page is checked against:

```
none  <  detect  <  best-effort  <  fail-to-ask  <  enforceable  <  enforced
```

The ordering axis is **how little the guarantee depends on someone being there.** A
`fail-to-ask` control does not let the action through, but a person has to answer and can say
yes; an `enforceable` one, configured, holds in an unattended CI run where there is nobody to
ask. That is the whole reason `fail-to-ask` ranks below `enforceable` despite being the
stronger *default* posture, and it is the placement to argue with if you disagree.

`detect` — the control observes but cannot block — has a rank so that a control chock does
**not** ship can be graded on the same ladder, but it is never a verdict in
`.chock/coverage.json`: an agent only gets an in-agent surface here once agentseam confirms it
can block there, and a row that stopped confirming that is a hard failure at import, not a
quiet downgrade to observation. `enforced-at-commit`, `advisory` and `disabled` have **no**
rank at all, deliberately: a git hook and an in-agent hook are different mechanisms, and a
number comparing them would invent a scale that does not exist.

> **Why the ladder needed a fourth word, and what it costs us to say so.** The five-word
> vocabulary grades on one axis: what the *host* does when our hook never runs. It therefore
> gave the same word — `best-effort` — to a control that degrades to silently allowing and to
> one that degrades to prompting a human. Those are not the same promise, and the second is
> strictly stronger. A grading layer that cannot rank a control above ours is not measuring
> anything, so the distinction is now derived from two inputs rather than one: the host's
> block behaviour and fail mode (from agentseam's matrix), and the control's own degradation
> (`compile.levels.CONTROL_DEGRADES_TO`).
>
> **Chock's own guard is a mixed control, so it is graded at its weakest path.** Of the five
> ways `gate.guard_runner.evaluate` can fail to reach a verdict, two now ask — the guard
> crashed, or it timed out — and three still allow, because they are preconditions rather
> than anomalies. The section [What happens when the guard cannot decide](enforcement-surfaces.md#what-happens-when-the-guard-cannot-decide)
> gives the per-path reasoning and the per-client evidence. `DEGRADES_TO_DENY`'s own rule
> settles the grade: a control mixing the two is declared at its weakest path, so
> `CONTROL_DEGRADES_TO` stays `allow`, chock's `pre-tool-use` and `agent-hooks` stay at
> `best-effort` on every client whose hook fails open (Cursor, which can be configured to fail
> closed, reaches `enforceable`), and this level still names something we do not earn. That is the intended
> result: the ladder is only worth trusting where it flatters us if it can also report that
> we are behind — including when we have genuinely improved and still fall short.

> **`enforced` is raised by the install step, not by `compile`.** Compiling writes a
> fragment; installing merges it into `.claude/settings.json` / `.cursor/hooks.json` and
> vendors the adapter that feeds the agent's JSON payload to the guard. Every `chock sync`
> runs that install step (`install-hooks` is its alias), so the documented adopter flow
> wires the guards it compiles. The claim is made by the step that performs the wiring, so
> it cannot get ahead of the mechanism. `ci-gate`'s contribution to `enforced-at-commit`
> follows the identical rule with `install-ci` in place of the hook installers.

> **The SessionStart arm hook is wiring, not a surface.** `chock sync` also installs a
> `SessionStart` entry (running the vendored `.chock/bin/claude_code.py`) into
> `.claude/settings.json`. It carries no coverage claim: its only job is re-installing the
> git hooks on a fresh clone — git never clones them — or printing the `chock sync`
> command into the session context when it cannot. See
> [Arming a fresh clone](adopting.md#arming-a-fresh-clone).

Example for `protect-main-branch`, whose gate declares `on: [commit, push]` and so targets
git-hook + CI + ambient-rule + managed-setting (for which the compiler writes nothing), with no pre-tool surface at all. Every agent
reaches the same grade, because the git hook is what earns it:

```json
{
  "protect-main-branch": {
    "claude":  { "level": "enforced-at-commit", "basis": null, "witnessed": false },
    "cursor":  { "level": "enforced-at-commit", "basis": null, "witnessed": false },
    "copilot": { "level": "enforced-at-commit", "basis": null, "witnessed": false },
    "aider":   { "level": "enforced-at-commit", "basis": null, "witnessed": false }
  }
}
```

## Reading the coverage report

`chock compile <id>` (and `init`) write `.chock/coverage.json`. Treat it as the source
of truth for "where does this guarantee actually hold?" — it's the foundation for the compliance
attestation on the [roadmap](roadmap.md).

Each cell is `{"level", "basis", "witnessed"}`, printed as `best-effort (vendor-docs)`. The level
is the weaker of the matrix word and the ceiling of the weakest basis it rests on:

| Weakest basis under the grade | May back at most |
| :--- | :--- |
| `live-run` | `enforced` |
| `live-run-partial` | `enforceable` |
| `vendor-source`, `vendor-docs`, `third-party-install` | `best-effort` |
| `inherited` | `detect` — unreportable, so the cell reads `none` |

`witnessed` is true only where `src/chock/data/witnesses.json` records chock seeing that surface
block in that vendor's real client — distinct from **tested** (`src/chock/data/claims.json`, our
suite against our runtime). Neither ever raises a level: evidence caps a claim, never grants one.
