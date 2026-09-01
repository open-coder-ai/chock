# Chock changelog

## Unreleased

- **agentseam 0.2.0, and the claim table now separates wire words from semantics.** The
  dependency pin moves from 0.1.1 to 0.2.0 (the post-ACS release: canonical outcome
  `escalate`, `ask` kept only as a deprecated alias). Under 0.1.1 chock's claim table
  validated its `verdict` field against agentseam's canonical constants and derived the
  fail-to-ask lift by `verdict == ASK` -- correct only because canonical and wire words
  coincided. Each `src/chock/data/claims.json` row now records BOTH the word witnessed on
  the vendor's wire (`verdict`, validated against a chock-owned wire vocabulary that a
  live-runtime test recomputes from fixtures) and an explicit `honours` boolean; the lift
  derives from `honours` alone, and a mutation test pins that equality with any verdict
  constant fails. The vendored runtimes speak agentseam's canonical words
  (`guard_runner.VERDICT_ESCALATE`, `Decision.escalate`) and every runtime fixture runs
  with `-W error::DeprecationWarning`, so a deprecated spelling cannot ship silently.
  No behavior change: a crashed guard still asks where it asked and codex still gets its
  deny, and no coverage word moves.

- **Coverage cells now carry their evidence, and a witness ledger replaces hand-asserted
  posture prose.** Each `.chock/coverage.json` cell is `{level, basis, witnessed}` rather than
  a bare word, and every report prints the pair -- `best-effort (live-run)`. The level is
  `min(matrix word, cap(weakest basis the grade rests on))`, so a strong word can never sit on
  weak evidence: `vendor-docs` backs `best-effort` at most, `inherited` backs nothing
  reportable. **No day-one word changes** -- every basis chock grades on today clears its cap;
  the cap's bite is the future case. Evidence is a ceiling, never a source: capability is read
  from `agentseam.matrix` alone, so no evidence record can grant a gate a matrix row denies.
  chock's own live observations move out of the packagers' prose into
  `src/chock/data/witnesses.json` (`{agent, surface, client, date, method}`, partial rows
  refused at load), and the "witnessed blocking on ..." phrase in a package posture is now
  rendered from that row -- delete the row and the claim disappears with it. Cursor's posture
  therefore names the client and date it was witnessed on instead of "a real install".
  `tested` (our suite against our runtime, `src/chock/data/claims.json`) stays distinct from
  `witnessed`: the `fail-to-ask` lift now requires a TESTED honours-ask claim naming the
  fixture that proves it, which is also the table the runtime test parametrizes over, so a
  claim cannot be edited up without that test failing.

- **Runtime: a guard that RAN and could not decide now asks for confirmation instead of
  allowing silently.** `gate.guard_runner` had five "could not determine" paths and answered
  all five the same way -- allow, with a line on stderr the agent sees and the developer
  usually does not. Two of them are now an `ask`: the guard crashed (any exit code that is
  neither 0 nor 1) and the guard hit its 30-second timeout. Both mean the control was
  installed, reachable and runnable and still produced no answer, which is anomalous rather
  than routine.
  The other three still allow, deliberately: a command POSIX `shlex` will not tokenize is
  common and usually benign, an empty command has nothing to check, and a machine with no
  usable `bash` is uniform across every command rather than a fact about this one. Oversight
  capacity is finite, and a control that prompts on all five would train a developer to click
  through the prompts that matter.
  What an `ask` becomes is per-client and no client turns it into a silent allow: Claude Code
  and VS Code agent mode prompt (VS Code's `ask` overrides its own auto-approve), Cursor's
  `beforeShellExecution` honours `permission: "ask"`, and Codex CLI -- whose parser rejects
  `ask` outright and then fails open on the response it rejected -- gets a deny instead. The
  per-client evidence is cited to vendor source and vendor docs at named refs in
  `docs/enforcement-surfaces.md`.
  **No coverage grade moves.** A control is only as strong as its worst degradation and three
  paths still allow. The plugin descriptions, the marketplace README text and
  `docs/enforcement-surfaces.md` are corrected to state the split rather than a flat
  "fails open"; `gate.guard_runner.evaluate` now returns `(outcome, reason)` or `None`.

- **Fixed: a guard that timed out wrote the command it was gating -- credentials included
  -- to stderr.** `subprocess.TimeoutExpired.__str__` embeds the argv it was given, which
  for `gate.guard_runner.run_guard` is bash, the guard script, and every token of the
  command. Printing it reached the agent's own transcript, which is exactly what the same
  function's parse-failure branch and `log_outcome` both refuse to do, and for the same
  reason: commands routinely carry bearer tokens and passwords. The timeout branch now
  reports the timeout alone. `OSError` and `UnicodeError` keep their detail -- those name
  the interpreter and an offset, not the command.
- **Coverage taxonomy: a fourth in-agent level, `fail-to-ask`, and an ordering.** The
  vocabulary graded on one axis -- what the HOST does when our hook never runs -- so a
  control that degrades to silently allowing and one that degrades to prompting a human
  both read `best-effort`. Those are not the same promise, and a grading layer that cannot
  rank a control above ours is not measuring anything. The grade is now derived from two
  inputs: the host's block behaviour and fail mode (agentseam's matrix) and the control's
  own degradation (`compile.levels.CONTROL_DEGRADES_TO`). `compile.levels.level_rank`
  orders the in-agent ladder (`none` < `detect` < `best-effort` < `fail-to-ask` <
  `enforceable` < `enforced`) and deliberately refuses to rank `enforced-at-commit`,
  `advisory` and `disabled` against it -- different mechanisms, no honest common scale.
  **No existing grade changed**, and none moves with the ask above either: a mixed control
  is declared at its weakest path, and three of the guard's five undecided paths still
  allow, so `pre-tool-use` and `agent-hooks` stay at `best-effort`. The ladder carries a
  word for something chock does not fully do, which is the point.
- **Docs: stale enforcement grades corrected.** `docs/agentic-risk-coverage.md`,
  `docs/concepts.md`, `docs/architecture.md` and `docs/compatibility.md` still published
  `enforced` for an installed in-agent control and `unsupported` for the empty verdict --
  both superseded by 0.7.0's finer vocabulary and neither checked by anything. The level
  table in `docs/enforcement-surfaces.md` and its ordering are now bound to
  `compile.levels` by `tests/test_surface_doc_matches_code.py`, so this class of drift
  fails a test instead of aging in place.
- **Internal: the level vocabulary moved to `chock.compile.levels`.** `surfaces.py` says
  which surfaces exist per agent; how strong a control on one of them is, is a different
  question and now a different module.
- **Packaging: every published plugin package now carries its own `LICENSE`.** The
  distribution repos hold a licence at the root only, so a plugin directory copied out of one
  arrived with no terms attached. The notice is derived entirely from the policy's own
  `provenance` -- licence from `license`, holder from `author`, year from `created_at` (or
  `updated_at`) -- never from this project's own `LICENSE`, because `chock plugin build` runs
  on anybody's policies and stamping open-coder-ai's copyright into a third party's package
  would be a false claim in the one file where it matters. Nothing is written when the notice
  cannot be derived (a licence whose text chock does not ship, or no year): a missing
  `LICENSE` is a visible gap, an invented one is not. Emitted for `claude`, `codex`,
  `cursor`, `copilot`, and for `agent-plugins` when it builds into a distribution directory
  -- never for the in-place `agent-plugins` build, whose target is the adopter's own
  `.agents/policies/<id>/`.
- **Packaging: the Codex manifest gains its `interface` block.** `.codex-plugin/plugin.json`
  now carries `interface{displayName, shortDescription, composerIcon}`, which directory
  listings render and score. Every field is derived: `displayName` from the policy's own
  `name`, `shortDescription` from the first sentence of its description (the full ones run
  past 900 characters, and the manifest `description` additionally carries the posture
  suffix, which is an enforcement claim rather than a summary), and `composerIcon` from the
  icon this emitter now writes into the package at `assets/icon.svg`. No other field in the
  block has a source in a policy manifest, so none is emitted.
- **Packaging: the emitted icon ships as package data.** `chock/plugin/data/icon.svg`,
  byte-identical to `docs/assets/logo.svg` and 512x512 by its viewBox, pinned in both
  directions by tests -- against the logo it was copied from, and against the built wheel,
  because `docs/` is not in the wheel and package data that is not declared silently is not
  either.
- **Internal: `chock/plugin/listing.py`.** What a listing needs from a package (icon,
  licence, display metadata) is a different question from what a client needs to load it, and
  `build.py` and `codex.py` were both over the 300-line review budget with the two mixed.

## 0.7.0 — Migrate primitives-generation to agentseam

BREAKING-ISH: chock's file layout, coverage vocabulary, and vendored runtime bytes all
change. `agentseam==0.1.0` is a real dependency (staged, not yet published — CI on this
change stays red by design until go-live; see the PR). Every adopter's next `chock sync`
rewrites `.chock/bin/`, `.claude/settings.json`, `.cursor/hooks.json`, and most per-agent
instruction files; some previously-written instruction files (for agents that read
`AGENTS.md` natively) are deleted outright, and `coverage.json` re-grades several
enforcement claims to a more honest, finer-grained word. All five migration-map axes land
in this release (owner decision #7, "Option B"); the full accounting is in the wave's
report, `plan/spine-a/reports/w7.md` on `open-coder-ai/org-plan` (private).

- **Runtime: vendored PreToolUse/SessionStart runners are now agentseam's bundle, not a
  hand-written cross-vendor adapter.** `.chock/bin/pretooluse.py` and
  `.chock/bin/sessionstart.py` are gone, replaced by `.chock/bin/claude_code.py`,
  `.chock/bin/cursor.py`, and `.chock/bin/vscode_copilot.py` — one self-contained,
  stdlib-only file per agent (`agentseam.bundler.bundle()` plus chock's own guard-running
  handler spliced in, see `gate/runtime_bundle.py`), instead of one file that sniffed which
  vendor sent a payload by its shape. Claude Code's deny now rides entirely in the JSON
  response body on a clean exit rather than exit code 2 — a deliberate, verified
  improvement (avoids a PowerShell-wrapper exit-code collapse and a command-line leak into
  the UI on some vendors), not a regression. Plugin packages (`chock plugin build` for
  claude/cursor/copilot/codex) ship the matching per-agent runtime instead of a shared one.
- **Runtime: `installed_*_policy_ids` keeps its content-comparison identity, verified
  against agentseam's own new opt-in mode.** agentseam's `install()`/`installed()` gained a
  content-comparison mode this wave (built by a prior worker specifically so a
  multi-fragment consumer like chock would not have to keep re-deriving it). chock's own
  three `installed_*_policy_ids` functions keep their existing, already-correct
  content-comparison logic rather than delegating to it: agentseam's mode does an exact
  string compare with no hook for machine-independent normalization, and chock's committed
  `.claude/settings.json` must compare equal across machines with different baked
  interpreter paths — delegating would have reintroduced the exact cross-machine
  coverage-flip bug `_normalize_fragment` exists to prevent. The required behavior (a
  guard's compiled fragment changing drops its installed claim) is intact and tested.
- **Permissions: `claude_managed.py` is unchanged, on verified evidence.** Checked directly
  against Claude Code's own documentation (`code.claude.com/docs/en/permissions`, read
  2026-08-29): permission rules cannot match a tool's content field at all — the docs name
  this explicitly and say Claude Code rejects an attempt to do so at parse time — and a
  request for regex/content matching there was closed "not planned" upstream
  (`anthropics/claude-code#37509`). `scan-secrets`'s regex-based managed-setting fragment
  has no equivalent in `agentseam.permissions.plan()`'s model and none is being forced
  through; no protection changes.
- **Instructions: whole-file branded templates are gone, replaced by agentseam's
  marker-block / shared-file model (owner decision #8).** Most agents chock scaffolds for
  read `AGENTS.md` natively (`agentseam.instructions.reads_shared()`) and now get no
  dedicated file at all: `.cursor/rules/*.mdc`, `.cursorrules`, `.windsurf/rules/*.md`,
  `.windsurfrules`, `codex.md`, `.kimi-code/AGENTS.md`, `.github/copilot-instructions.md`,
  `.gemini/GEMINI.md`, and `.github/agents/*.agent.md` are no longer written — their
  content lives only in `AGENTS.md`'s own managed pointer block. Agents that do not read
  `AGENTS.md` natively (claude, aider, devin, grok, replit, tabnine, antigravity) get a
  marker-delimited block in their own file instead of a whole-file claim, so adopter
  content elsewhere in that file survives untouched — coexistence a whole-file template
  could never offer. Claude Code's own file moves from `.claude/CLAUDE.md` to `CLAUDE.md`
  at the repo root (agentseam's preferred path). Aider is the one exception: agentseam's
  model cannot express `.aider.conf.yml` (a real config file, not a marker-block target),
  so chock still ships it directly alongside the marker block it writes into
  `CONVENTIONS.md`.
- **Coverage: `coverage_level()` adopts agentseam's five-tier vocabulary for in-agent
  surfaces (owner decision #9).** `pre-tool-use`/`agent-hooks`, once installed, no longer
  read a flat `enforced` — they return whichever of `enforced`/`enforceable`/`best-effort`
  the mapped agent's own verified capability row earns
  (`agentseam.matrix.enforcement_level`). claude_code's PreToolUse is FAIL_OPEN, so it now
  reads `best-effort`, never `enforced`; cursor's is FAIL_CONFIGURABLE, so it reads
  `enforceable`. `enforced-at-commit` and `advisory` stay chock's own words for its
  git-hook/CI-gate and ambient-rule surfaces, which are outside agentseam's per-agent-hook
  model; `unsupported` is renamed `none`, agentseam's own word for the same claim. A
  companion `open-coder-ai/chock-catalog` PR re-renders the seven guard-shipping policies'
  docs and coverage matrix to the same honest wording (their own descriptions already said
  "best-effort"; only the machine-readable label was overclaiming).

## 0.6.0 — Agent-hooks `py` fallback and INT-3 verb list

MINOR: the agent-hooks emitter output changes, so an adopter's next `chock sync` /
`chock plugin build` rewrites `.github/hooks/*.json`. No credited enforcement surface
changes — the guard runs the same, just with one more way to find an interpreter.

- **Agent-hooks Bash resolver adds the `py` launcher fallback.** The Bash branch resolved
  `command -v python3 || command -v python`; the PowerShell branch already tried `py`. On a
  Windows checkout where only the `py` launcher is on PATH (no `python3`/`python`), the Bash
  hook exited "no python interpreter found" and the guard failed open. It now also tries
  `py`, matching the PowerShell branch, so the two agree about where enforcement holds.
- **INT-3 recognises `pin` as a verb.** `pin` was missing from the verb-prefix set, so a
  policy id like `pin-github-actions` drew a spurious "does not start with a verb" warning
  even though pinning is exactly what it does. Added `pin`; `block`/`protect`/`scan`/`verify`
  were already there.

## 0.5.0 — Managed-setting and SKILL honesty

MINOR: the Claude managed-setting emitter and the generated SKILL note change, so an
adopter's next `chock sync` / `chock plugin build` rewrites those artifacts. No credited
enforcement surface changes — both are non-credited/advisory outputs being brought into
line with what they can actually deliver (do-not-claim, applied to the emitter itself).

- **`protect-main-branch` managed-setting is now empty.** It previously emitted a
  branch-blind command-text deny (`commit.*\b(main|master)\b`) that missed a plain
  `git commit` on main and false-positived on "main" in a message. A static managed
  setting cannot resolve branch state, so the honest managed-setting for branch
  protection carries no deny — enforcement lives in its git-hook and ci-gate surfaces,
  which do read the branch.
- **`scan-secrets` managed-setting aligned to the gate.** Added `jks|keystore` to the
  credential-file pattern and more high-confidence credential prefixes (xoxb, sk/rk_live,
  sk-ant, AIza, npm_) so the in-session echo is less of a silent subset of the git-hook.
  Kept lookahead-free for cross-client regex-engine safety; the git-hook remains
  authoritative.
- **SKILL advisory note is conditional on artifact.** A `rule` (advise-tier) policy no
  longer claims it "becomes a git hook that exits non-zero" when compiled — it ships rule
  text and stays advisory. Only `hook` policies carry that line; guard-script policies
  still get the enforced note in the per-client plugin formats.

## 0.4.0 — Witnessed enforcement on Cursor and Codex

MINOR: plugin packaging output changes (spec fixes and three new formats), and the
vendored PreToolUse adapter changes -- the deny-dialect and payload-decoding fixes below
mean an adopter's next `chock sync` rewrites it. Every other compiled enforcement
surface is unchanged.

- **Per-vendor marketplace indexing**: `chock marketplace build --tree cursor|codex`
  indexes a vendor's own format tree with the index file its client actually reads --
  Cursor's `.cursor-plugin/marketplace.json` in Cursor's schema, and for Codex the
  legacy `.claude-plugin/marketplace.json` shape it was witnessed consuming from git
  marketplaces -- so each vendor-named distribution repo carries exactly one vendor's
  packages instead of every format tree. Default (`--tree claude`) is byte-unchanged.
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
