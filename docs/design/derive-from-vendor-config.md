# Deriving chock's per-vendor surface from agentseam's vendor config

Design document (W36, design only — no implementation). chock citations are at main
`bb25bbe`; agentseam citations are at `427fc26`, the commit that merged the approved
dialect-families design (`docs/design/dialect-families.md` there, cited below as DF §n).
That design's D2 wave creates `src/agentseam/data/vendors/<agent>.json`; this document
designs what chock deletes, derives, and keeps once that config exists. It consumes the
upstream design and must not fork it: no fact recorded in a vendor entry is ever
re-recorded here.

Legend: **[v]** verified by recount/execution at the pins; **[r]** reported upstream
(brief or orchestrator), not independently re-derived; **[h]** hypothesis for
implementation to verify.

## 0. The goal that sizes everything

chock enforces in-agent on 4 chock agent names today — `claude` + `cursor` via
pre-tool-use, `copilot` + `vscode` via agent-hooks (`compile/surfaces.py:44-56`) — which
map to **3** agentseam vendors (`claude_code`, `cursor`, `vscode_copilot`,
`compile/levels.py:8-13`). agentseam adapts **12** (`matrix.adapted_agents()` at the pin
**[v]**). The design is therefore judged on what vendors #5–#12 cost, not on cleaning up
today's 4: the newly reachable set is **9 vendors** (12 − 3): `antigravity`, `codex_cli`
(reachable today only through its plugin store, not the repo-level hook surface),
`devin`, `gemini_cli`, `grok`, `junie` (absent from chock entirely today **[v]** — no
`SURFACE_AGENTS` or `CHOCK_AGENT` row), `kimi_code`, `tabnine`, `windsurf`. The dispatch
brief said 8; the recount says 9, because `copilot`/`vscode` are one vendor and `junie`
is missing today.

Data literals are only ~8% of `src/chock` **[r]** — extraction is not the lever;
derivation is. Most per-vendor bulk here is five hand-written modules per vendor doing
the same three jobs with different words in them.

## 1. The derivation map

Source-of-truth vocabulary:

- **DA** — derives from agentseam: the vendor config entry (DF §3.2: `config_path`,
  `events`/`wire_events`, `hook_entry`, `tools`, `verdicts.gates`), the capability
  matrix (`matrix.py`), or `packaging.py`. chock reads it; chock never re-records it.
- **SD** — chock-store-data: marketplace manifest schema facts per store; lives in a
  chock data table because agentseam has no marketplace concept.
- **CC** — chock-code: policy logic that stays code (the line of DF §3.1 applies
  unchanged: word/key/flag/list-order is data; branching is code).

### 1.1 `compile/emitters/`

| fact | today | class | source once vendor config exists |
| :--- | :--- | :--- | :--- |
| guard-script convention + legacy map | `claude_pretooluse.py:10-24` | CC | chock policy layout, vendor-free |
| hook matcher `"Bash"` | `claude_pretooluse.py:27` | DA | `claude_code` shell-tool vocabulary (adapter `SHELL_TOOLS`, agentseam `adapters/claude_code.py:49`) → config `tools.shell` |
| `TIMEOUT_SECONDS = 30` | `claude_pretooluse.py:28` | CC | chock's own budget, same for every vendor |
| repo-root token `${CLAUDE_PROJECT_DIR}` | `claude_pretooluse.py:51-53` | DA | vendor wire fact; **schema gap** — DF §3.2's `hook_entry` has no repo-root-token field yet, D2 must carry one **[h]** |
| adapter path `.chock/bin/claude_code.py` | `claude_pretooluse.py:53` | CC | derived: `.chock/bin/` (chock convention) + agent id + `.py` |
| Claude fragment shape `{matcher, hooks:[{type,command,timeout}]}` | `claude_pretooluse.py:55-64` | DA | `hook_entry` wrapper `hooks_map` — agentseam `adapters/_common.py:9-20` renders this exact shape today |
| Cursor entry shape + event `beforeShellExecution` | `claude_pretooluse.py:70-76` | DA | cursor `REVERSE_EVENT_MAP` + `hook_config` (agentseam `adapters/cursor.py:218-228`) |
| VS Code shell matcher `"bash\|powershell\|pwsh\|sh\|shell"` | `agent_hooks.py:11` | DA | vendor tool vocabulary; **gap**: agentseam's `vscode_copilot` records no `SHELL_TOOLS` today **[v]** — chock's witnessed matcher is the evidence D2 should ingest |
| interpreter-discovery bash/powershell templates | `agent_hooks.py:14-31` | CC | chock policy (find python, refuse silently-missing); the powershell variant should reuse agentseam `adapters/_windows.py` rather than a second copy |
| VS Code entry keys `type/matcher/timeout/timeoutSec/bash/command/powershell/windows` | `agent_hooks.py:45-54` | DA | `hook_entry` `entry_extra`; **divergence** — agentseam emits `{type, command, windows}` (`adapters/vscode_copilot.py:185-193`); see §1.5(4) |
| Claude managed-settings fragment schema | `claude_managed.py:14-40` | CC | claude-only surface, policy-conditional content; no config equivalent upstream |
| `ambient` / `ci` / `git_hook` / `mcp_gateway` emitters | whole files | CC | agent-agnostic **[v]** (no vendor token in any of them) |

### 1.2 `hooks/installers.py`, `hooks/*_install.py`

| fact | today | class | source |
| :--- | :--- | :--- | :--- |
| git dispatcher/validate-hook machinery | `installers.py` (whole file) | CC | vendor-free **[v]** |
| `.claude/settings.json` | `pretooluse_install.py:14` | DA | `config_path` (agentseam `adapters/claude_code.py:181`) — duplicated in both repos today |
| `.cursor/hooks.json` | `cursor_install.py:18` | DA | `config_path` (agentseam `adapters/cursor.py:231`) — duplicated |
| `.github/hooks/` directory | `agenthooks_install.py:11` | DA | dirname of `vscode_copilot` `config_path` (agentseam `adapters/vscode_copilot.py:196`); the `chock.json` filename stays CC (chock owns its own file beside `agentseam.json`) |
| event key `preToolUse` | `agenthooks_install.py:42` | DA | `wire_events`; **divergence** — agentseam spells it `PreToolUse`; see §1.5(4) |
| `version: 1` envelope (cursor) | `cursor_install.py:78` | DA | cursor `hook_config` envelope (agentseam `adapters/cursor.py:228`) |
| ownership markers `/.chock/bin/<agent>.py` | `pretooluse_install.py:16`, `cursor_install.py:20`, `sessionstart_install.py:20` | CC | derived from agent id; the marker convention is chock's |
| interpreter baking / normalize / keep-if-runs merge logic | `pretooluse_install.py:21-59,105-130` | CC | chock policy, shared verbatim by all installers already **[v]** (`cursor_install.py:11-15` imports it) |
| SessionStart arm fragment + orchestration | `sessionstart_install.py:22-30`, `gate/runtime_bundle.py:71-106` | CC | claude-only chock behaviour; event name + shape from config, the branch stays code |
| `RUNTIME_FILENAME` map | `runtime_vendor.py:9-13` | CC | delete: it is `f"{agent}.py"` for all three rows **[v]** |
| `RUNTIME_AGENTS` tuple | `gate/runtime_bundle.py:17` | DA | derive: adapted vendors chock wires in-agent (§3); `render()` itself is already agent-generic **[v]** (`runtime_bundle.py:123-135` wraps `bundler.bundle(agent)`) |
| `VENDORED_RUNTIMES` bundle rows | `vendored.py:9-11` | DA | same derivation |
| per-vendor installer wiring in `hooks/install.py:67-95` | three copied try/except blocks | CC→one loop | one generic installer over the derived vendor set |

### 1.3 name maps, surfaces, coverage

| fact | today | class | source |
| :--- | :--- | :--- | :--- |
| `MATRIX_AGENT` (4 rows) | `compile/levels.py:8-13` | DA | delete; one alias table (chock name ↔ agentseam id) is data, everything else uses agentseam ids |
| `CHOCK_AGENT` (14 rows) | `scaffold/adapters.py:14-29` | DA | the same single alias table; today it and `MATRIX_AGENT` are two hand-kept maps that can drift from each other **[v]** |
| `SURFACE_AGENTS` (14 hand-rows) | `compile/surfaces.py:21-41` | DA | derive: every matrix agent gets `{ambient, git-hook, ci-gate}`; in-agent membership per §3. `aider`/`replit` (tier `none`/`unadapted` **[v]**) stay advisory-only automatically; `junie` appears automatically |
| in-agent membership assertion | `compile/surfaces.py:44-56` | DA | subsumed by the §3 derivation + consistency test |
| `installed_for` / `agent_hooks_for` dicts | `compile/compiler.py:129-133` | DA | one generic `installed_policy_ids(vendor)` over the derived set |
| in-agent level words | `compile/levels.py:57-67` | DA (already) | unchanged: `matrix.enforcement_level` is already the source **[v]**; gains `honours_ask` from `verdicts.gates` (§3.2) |

### 1.4 `plugin/*.py` (the four store packagers)

Recount of the orchestrator's measurement, method: per store, extract the five role
functions, normalize the store token, strip docstrings, hash
`ast.dump(include_attributes=False)` **[v]**:

| role | distinct / 4 | lines (4 stores) | class |
| :--- | :--- | :--- | :--- |
| `stale_<store>_files` | 1 | 48 | CC — one parametrized function; `OWNED_SUBTREES` becomes store data (`claude.py:121`, `codex.py:146`, `cursor.py:137`, `copilot.py:117`) |
| `build_<store>_plugin` | 1 | 62 | CC — one function |
| `<store>_plugin_differences` | 1 | 52 | CC — one function |
| `build_<store>_manifest` | 4 | 85 | SD + renderer — §5 |
| `<store>_plugin_files` | 4 | 154 | SD + DA + renderer — §5 |

Already-derived facts (keep): store layout, skill/hooks/executable path templates and
plugin-root tokens all come from `agentseam.packaging` (`plugin/claude.py:26-27`,
`plugin/codex.py:25-28`, `plugin/cursor.py:26-29`, `plugin/copilot.py:25-29`) —
except `codex.py:31` and `cursor.py:32`, which hardcode `"scripts/{name}"` instead of
`packaging.supports(agent, EXECUTABLE)` **[v]**: an in-chock half-derivation to finish.

| fact | today | class | source |
| :--- | :--- | :--- | :--- |
| hook event per store (`PreToolUse`, `beforeShellExecution`) | `codex.py:29`, `cursor.py:31`, `claude.py:105`, `copilot.py:101` | DA | `wire_events` |
| plugin hooks-file shape per store | `claude.py:103-113`, `codex.py:128-137`, `cursor.py:125-128`, `copilot.py:99-108` | DA | same `hook_entry` rendering as the repo-level surface — the shapes are identical today **[v]** |
| `MANIFEST_KEYS` ordering | `codex.py:33-44`, `cursor.py:34-46`, `build.py:22-33` | SD | store schema data |
| posture strings (enforced/advisory, witness claims) | `claude.py:29-42`, `codex.py:46-64`, `cursor.py:48-63`, `copilot.py:31-50` | SD + §3 | templates in store data; the *witness* clauses fill from the ledger (§3.3), never hand-asserted |
| `COPILOT_NAMESPACE`, `NAMESPACE`, `SCHEMA_URL`, name grammar | `copilot.py:27`, `build.py:15-48` | SD | store schema data |
| guarded hook command (unresolved root ⇒ allow) | `copilot.py:53-59` | CC | fail-posture policy + DA `plugin_root` token |
| marketplace tree manifests | `marketplace.py:16-32` | DA | `packaging.layout(agent)["manifest"]` — duplicated verbatim in both repos today **[v]** (`marketplace.py:18` = packaging's `claude_code` manifest path) |
| marketplace index styles, lockfile, catalog page | `marketplace.py:56-157` | SD/CC | store data (index style) + chock code |

### 1.5 The drift class this kills — facts recorded in BOTH repos today [v]

1. `.claude/settings.json` — `hooks/pretooluse_install.py:14` ≡ agentseam
   `adapters/claude_code.py:181`.
2. `.cursor/hooks.json` — `hooks/cursor_install.py:18` ≡ agentseam
   `adapters/cursor.py:231`.
3. `.github/hooks/` — `hooks/agenthooks_install.py:11` ≡ dirname of agentseam
   `adapters/vscode_copilot.py:196`.
4. **Live disagreement**: chock writes VS Code hooks under `preToolUse`
   (`hooks/agenthooks_install.py:42`) with `bash`/`powershell`/`timeoutSec` entry keys
   (`compile/emitters/agent_hooks.py:45-54`); agentseam's `vscode_copilot` renders
   `PreToolUse` with `{type, command, windows}` (`adapters/vscode_copilot.py:185-193`).
   chock's spelling is backed by a witnessed deny in VS Code agent mode
   (`plugin/copilot.py:31-40`); agentseam's row is `live-run-partial`. D2's
   `wire_events`/`hook_entry` for `vscode_copilot` must record the witnessed shape once,
   with evidence — until then the two repos publish different wire bytes for the same
   vendor surface.
5. **Live disagreement**: agentseam's cursor `hook_config` sets `failClosed: true` on
   gate entries (`adapters/cursor.py:225-226`); chock's emitted cursor entries carry no
   `failClosed` (`compile/emitters/claude_pretooluse.py:70-76`,
   `hooks/cursor_install.py:78`, `plugin/cursor.py:125-128`) — yet cursor's matrix row
   is the only `fail=configurable` one and grades `enforceable` **[v]**. chock is
   leaving its strongest honest grade unclaimed at the wire level, or claiming it
   without setting the flag — either way the fact must live once, in the vendor entry.
6. Shell-tool vocabulary: `"Bash"` (`compile/emitters/claude_pretooluse.py:27`) ≡
   agentseam `adapters/claude_code.py:49`; the VS Code matcher (`agent_hooks.py:11`) has
   no agentseam counterpart yet (gap, §1.1).
7. Hook entry shapes: `{matcher, hooks:[{type,command,timeout}]}`
   (`claude_pretooluse.py:55-64`, `plugin/claude.py:103-113`, `plugin/codex.py:128-137`,
   `plugin/copilot.py:99-108`) ≡ agentseam `adapters/_common.py:9-20`.
8. Store manifest paths: `plugin/marketplace.py:18,23,28` ≡ `packaging.layout(...)`
   entries chock already imports two files away.
9. Windows powershell wrapping: `compile/emitters/agent_hooks.py:23-31` vs agentseam
   `adapters/_windows.py`.

## 2. Target shape

```
src/chock/vendors.py          # NEW ~60 lines: loads agentseam vendor config + matrix;
                              #   the alias table; derived enforcement set; nothing else
compile/emitters/in_agent.py  # NEW: one emitter; writes <agent>-hooks.json fragments
                              #   rendered from hook_entry (replaces claude_pretooluse
                              #   vendor parts + agent_hooks.py)
hooks/in_agent_install.py     # NEW: one installer (config_path + chock merge policy +
                              #   interpreter baking + ownership marker), replaces
                              #   pretooluse_install/cursor_install/agenthooks_install;
                              #   sessionstart_install stays (claude-only, CC)
plugin/store.py               # NEW: 3 shared roles parametrized + manifest renderer
plugin/data/stores/<store>.json  # NEW: SD per marketplace (§5)
```

Deleted: `plugin/{claude,codex,cursor,copilot}.py` (707 lines **[v]**), the three
installers (370 lines), the two vendor emitters (142 lines), `MATRIX_AGENT`,
`RUNTIME_FILENAME`, hand-rows of `SURFACE_AGENTS`/`CHOCK_AGENT`. Internal API breaks
are free under the release freeze; `chock check` invariants and the 300-line module
budget hold; wire output stays byte-identical through the refactor waves that precede
the vendor-config switch (§7), proven by the existing emitter-stability goldens
(`tests/test_emitter_stability.py`) plus new per-vendor golden fixtures.

The ACS vocabulary wave renames canonical decision words upstream (`ask`→`escalate`,
`rewrite`→`transform`, aliases kept). chock touches those words only through
`agentseam.contract`/`matrix` (`compile/levels.py:5-6`) **[v]**, so the rename reaches
chock as a pin bump, and nothing here hardcodes the old words.

## 3. Coverage honesty: grade = matrix row × witness ledger

### 3.1 The derivation

Membership first: vendor V gets the in-agent surface iff
`matrix.can_block(V, PRE_TOOL)` — the same predicate `surfaces.py:44-56` asserts today,
made generative instead of a guarded allowlist. A vendor whose row cannot block
(`aider`, `replit`, raw `copilot`, `zed` **[v]**) never gains an in-agent surface, no
matter what any config file says, because **the grading path reads capability from
`agentseam.matrix` only — never from the vendor config**. That is the consistency
property, and it is structural, not asserted: vendor config carries wire facts (paths,
shapes, words); the matrix carries capability with evidence (DF §3.3 keeps them apart
deliberately, so a config edit cannot widen a claim past the matrix in either repo).

The reported word stays what `in_agent_level` already computes
(`compile/levels.py:57-67`): `matrix.enforcement_level(V, PRE_TOOL)`, lifted to
`fail-to-ask` only when the host is `best-effort` *and* chock's guard degrades to ask —
which is itself only claimable when the vendor's pre-tool gate honours ask
(`verdicts.gates.pre_tool.honours_ask` in the vendor entry; hosts that degrade ask→deny
like `codex_cli` or ask→allow never earn it).

### 3.2 The witness ledger (chock-data, evidence-bearing)

Today chock's posture strings hand-assert witness ("witnessed blocking on Codex
Desktop, Windows, 2026-08-24", `plugin/codex.py:48-49`; "witnessed blocking on a real
install", `plugin/cursor.py:51`). Those claims are chock's own live evidence about
chock's own wiring — agentseam's matrix cannot carry them. They move to one data table —
`data/witnesses.json` under `src/chock` (new in C1) — rows of
`{agent, surface, client, date, method}`.
Rules:

- A "witnessed" posture template renders **iff** a ledger row exists for that
  vendor × surface AND the matrix row can block. No row → the unwitnessed template
  ("documented by the vendor; not witnessed by chock") renders, and `coverage.json`
  carries `{"level": <word>, "basis": <matrix basis>, "witnessed": false}`.
- The level *word* never depends on the ledger — the word is agentseam's
  evidence-graded claim and chock must not exceed **or** inflate it; the ledger only
  gates which *prose* chock adds on top.
- Adding a ledger row requires all evidence fields; the schema validator rejects
  partial rows (a typo'd row must fail loud, DF §5.1 discipline).

Consistency tests (all derivations, not presence checks — the chock#81 lesson): (a) the
derived in-agent set equals `{V : can_block(V, PRE_TOOL)}` recomputed in the test from
the matrix; (b) every "witnessed" phrase in emitted posture text maps to a ledger row
via the template engine (mutation: delete the row, the phrase must disappear and the
test must fail if it doesn't); (c) grading-path imports: `chock.vendors` grading
functions take matrix objects only — enforced by a test that grades a synthetic vendor
whose config claims gates its matrix row denies, and asserts the claim loses.

### 3.3 Day one for the 9 new vendors [v — matrix executed at the pin]

With the derived surface emitted and installed, before any hand-verification:

| vendor | tier | fail mode | basis | `pre_tool` observed | day-one report |
| :--- | :--- | :--- | :--- | :--- | :--- |
| antigravity | block | open | vendor-docs | no | `best-effort` · unwitnessed |
| codex_cli | block+rewrite | open | live-run-partial | yes | `best-effort` · unwitnessed for the repo-level hook; the existing plugin-store witness (2026-08-24) stays scoped to the plugin surface |
| devin | block+rewrite | open | vendor-docs | no | `best-effort` · unwitnessed |
| gemini_cli | block+rewrite | open | vendor-source | no | `best-effort` · unwitnessed |
| grok | block | open | vendor-docs | no | `best-effort` · unwitnessed (plus `needs_trust` caveat from its entry) |
| junie | block+rewrite | open | vendor-docs | no | `best-effort` · unwitnessed |
| kimi_code | block | open | vendor-docs | no | `best-effort` · unwitnessed; deny-only gates ⇒ never `fail-to-ask` |
| tabnine | block | open | vendor-docs | no | `best-effort` · unwitnessed, **plus** `vocabulary_basis: unverified` surfaced verbatim — its decision words themselves are unconfirmed upstream |
| windsurf | block | open | third-party-install | no | `best-effort` · unwitnessed (exit-code grammar, G5) |

And the ones that must never gain a claim: `aider`, `replit`, raw `copilot`, `zed` —
`can_block` false ⇒ no in-agent surface ⇒ `enforced-at-commit`/`advisory` only, exactly
today's words for installed git/CI/ambient surfaces (`compile/surfaces.py:85-92`).
`cursor` remains the only `enforceable` (fail-configurable) — contingent on chock
actually setting `failClosed` (§1.5.5).

## 4. The new-vendor walkthrough

"Vendor X lands in agentseam as `data/vendors/x.json`" (with a matrix row — D2's own
consistency tests require that pairing):

**X has no marketplace — zero chock code, zero chock data:**

1. Bump the agentseam pin (one line, `pyproject.toml`).
2. `chock sync` regenerates: X appears in the derived agent set (advisory surfaces
   always; in-agent iff its row blocks); instruction files via
   `agentseam.instructions`; an in-agent fragment rendered from X's `hook_entry`; a
   vendored runtime `.chock/bin/<agent>.py` via the already-generic
   `runtime_bundle.render(x)`; goldens regenerate (generated output, not code).
3. `coverage.json` reports X per §3.3: matrix word, matrix basis,
   `witnessed: false`. Posture text says "documented, not witnessed". Nothing defaults
   to a claim; the strongest thing an un-run vendor can say is agentseam's own
   evidence-graded word with the unwitnessed qualifier attached.
4. Witnessing later (a human or CI harness sees a real deny) = one ledger row.

**X also has a marketplace — one data entry:**

5. `plugin/data/stores/x.json`: manifest key order, static fields, posture templates,
   owned subtrees, index style. The hooks file inside the package renders from the same
   `hook_entry` as step 2 — not restated.
6. Golden fixtures for the built package; `chock plugin build --check` and
   `chock marketplace build` pick the store up from the data directory.
7. Renderer code changes **only** if X's manifest schema cannot be expressed by the
   §5 renderer — a measured criterion (a schema needing content-dependent branching),
   not a convenience door.

## 5. The two schema-bound roles, tested against the real schemas

Constraints on record (chock#87,
https://github.com/open-coder-ai/chock/pull/87): Agent Plugins 1.0 root manifests
(`copilot`, `agent-plugins`) are `additionalProperties: false` — one invented key
invalidates the manifest; Cursor's schema is likewise `additionalProperties: false` and
already carries `displayName`/`category`; Claude's schema is not vendored and unverified
keys are not a guess worth making; Codex's legacy schema tolerates the `interface`
block.

Can `build_<store>_manifest` become data + one renderer? Per-store analysis of what
actually differs **[v]**:

| store | beyond the shared core (`name/version/description/author/license/repository/keywords` + posture suffix) | expressible as data? |
| :--- | :--- | :--- |
| claude | nothing (`plugin/claude.py:57-77`) | yes — empty extras |
| codex | `interface{displayName, shortDescription, composerIcon}` + `skills` + `hooks` ref + icon asset (`plugin/codex.py:74-100`) | yes, with **named derivations** (DF's `reject_probes` pattern): `interface.displayName ← manifest.name`, `shortDescription ← first_sentence(description)` are engine functions referenced by name from data, not code-in-config |
| cursor | `displayName`, `category`, `skills`, `hooks` ref (`plugin/cursor.py:73-98`) | yes — static extras + named derivations |
| copilot | `$schema` + `extensions{NAMESPACE}` block surgery: drop `manifest` key, drop `coverage_without_chock` when enforced, add `hooks` (`plugin/build.py:70-99`, `plugin/copilot.py:62-72`) | mostly — the branching input is `enforced`, a renderer parameter, not payload content; the extensions-block construction itself is ~10 lines of store code **[h]** |

Verdict: one renderer driven by `{key order, static fields, named field derivations,
posture templates, enforced-mode deltas}`, plus at most one small store function for the
Agent Plugins extensions block. The `additionalProperties: false` schemas are an
argument **for** data: the renderer emits exactly the declared keys in the declared
order and nothing else, and the schema validation that chock#87 already runs in tests
becomes the mutation guard (an extra data key fails the vendored schema, loudly).

`<store>_plugin_files` follows: file set = manifest + skill (path from
`packaging.supports`) + optional license/icon (flags) + hooks file (`hook_entry`) +
adapter/guard scripts (`packaging` executable template). All four stores' versions are
this same sequence with different constants today **[v]**.

Size: `plugin/{claude,codex,cursor,copilot}.py` 707 lines + the four packagers' share
of `build.py` → `plugin/store.py` ≈ 220–280 lines + 4 store entries ≈ 40–60 lines each
**[h]** — implementation publishes real numbers next to these.

## 6. What vendors #5–#12 cost, both paths

Status quo, measured against what vendor #4 actually cost **[v]** — per vendor with a
store: a packager module (165–192 lines), an installer (67–162 lines), emitter wiring
(~70 lines), plus coordinated edits at ~10 sites: `SURFACE_AGENTS`, `MATRIX_AGENT`,
`CHOCK_AGENT`, `RUNTIME_FILENAME`, `RUNTIME_AGENTS`, `VENDORED_RUNTIMES`,
`compiler.py:129-133`, `hooks/install.py:67-95`, `plugin/cli.py:25-32`,
`marketplace.py:16-32` — **≈ 350–500 lines and 12 files touched, each edit a chance to
restate a vendor fact wrongly**. Times 8–9 vendors: ~3,500+ lines of hand-kept vendor
prose.

Designed path: **pin bump only** for a storeless vendor; **one store data entry +
goldens** for a vendor with a marketplace. The 12-site edit list is empty because every
site derives.

## 7. Sequencing against agentseam's D-waves

The release freeze covers both repos; breaking chock-internal APIs is free, `chock
check` invariants and the 300-line budget hold. agentseam waves per DF §6: D1 goldens,
D2 vendor config, D3–D5 family engines, D6 bundler.

| wave | delivers | blocks on | parallel with |
| :--- | :--- | :--- | :--- |
| C0 | 3-role packager collapse into `plugin/store.py` + store data; alias-table unification (`MATRIX_AGENT`+`CHOCK_AGENT` → one table); `RUNTIME_FILENAME` deleted; `marketplace.py` TREES → `packaging.layout`; `scripts/{name}` hardcodes → `packaging.supports` | nothing — agentseam 0.1.1 already ships `packaging` **[v]** | D1–D6, all |
| C1 | witness ledger + basis-qualified coverage + posture templating (§3); posture prose changes, wire bytes don't | nothing — reads today's `matrix` API | D1–D6, all |
| C2 | wire facts → vendor-config reads (config paths, events, hook entries, tool lists); one emitter + one installer; settles §1.5(4) and §1.5(5) with witness evidence recorded upstream | **D2 landed + released** (chock pins `agentseam==0.1.1` at `pyproject.toml:63`; a pin bump needs a release, freeze or not) | D3–D6 |
| C3 | derived `SURFACE_AGENTS` + in-agent extension to the 9 vendors; day-one coverage per §3.3; per-vendor golden fixtures for fragments and runtimes | C2; runtime bundles for new vendors work off today's `bundler.bundle` **[v]**, so D3–D6 are *not* blockers | D3–D6 |
| C4 | re-golden vendored runtimes against agentseam's engine-built bundles; byte-stability | D6 released | — |

Every C-wave lands green independently; C0/C1 are pure-chock refactors provable
byte-identical (C0) or prose-only (C1) by the existing goldens.

## 8. Test intent ledger

Survive re-targeted: the per-vendor suites (`test_claude_plugin.py`,
`test_cursor_codex_plugin.py`, `test_copilot_plugin.py`, `test_cursor_hooks.py`,
`test_agent_hooks.py`) become the store/installer conformance load over derived
output — none die. `test_coverage_is_derived.py`, `test_coverage_honesty*.py`,
`test_enforcement_matrix.py` extend to the derived agent set and the basis field.

Must be written: (1) the three §3.2 consistency derivations with their stated
mutations; (2) store-data schema validation, unknown keys fatal; (3) golden wire
fixtures per vendor × surface captured **before** C2 flips any read (the empty-diff
proof, agentseam D1's trick applied to chock); (4) a thirteenth-vendor test: a synthetic
agentseam vendor entry + matrix row must yield surfaces, fragments, coverage and (with
a synthetic store entry) a package with zero chock code edits; (5) a legitimate-edit
case per guard — a rewrapped posture paragraph must still pass. These mutations failing
is not a claim the class is closed.

## 9. Open questions carried as hypotheses

- **[h]** §1.1: D2's schema needs a repo-root token field (`${CLAUDE_PROJECT_DIR}`
  analogue) and a `vscode_copilot` shell-tool list; chock is the evidence donor for
  both. If D2 refuses wire facts chock needs, chock carries a small overlay table —
  same schema, chock-owned rows, consistency-tested for disjointness — rather than
  forking entries.
- **[h]** §5's copilot extensions-block function is the only store code predicted to
  survive; if implementation finds a second store needing code, the renderer's data
  vocabulary is drawn too narrow — revisit the vocabulary, don't grow store modules.
- **[h]** Whether chock should set cursor's `failClosed: true` (§1.5.5) is an
  enforcement-behaviour change with a real blast radius (a crashing guard starts
  blocking sessions); it needs an owner decision and a witnessed run, not a silent
  flag-flip during C2.
- **[h]** The 9 new vendors' guard runtimes assume agentseam's bundles speak each
  vendor's verdict grammar correctly under chock's `--guard` protocol
  (`gate/runtime_bundle.py:59-68` injects the same handler everywhere); windsurf's
  exit-code grammar (G5) is the case most likely to surprise — C3 must golden-test it
  first.
