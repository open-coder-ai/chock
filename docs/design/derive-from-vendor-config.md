# Deriving chock's per-vendor surface from agentseam's vendor config

Design document (W36, design only — no implementation). chock citations are at main
`bb25bbe`; agentseam citations are at `427fc26`, the merge of the approved
dialect-families design (`docs/design/dialect-families.md` there, cited as DF §n),
whose D2 wave creates `src/agentseam/data/vendors/<agent>.json`. This document designs
what chock deletes, derives, and keeps once that config exists; it consumes the
upstream design and never re-records a fact a vendor entry carries.

Legend: **[v]** verified by recount/execution at the pins; **[r]** reported upstream,
not independently re-derived; **[h]** hypothesis for implementation to verify.

## 0. The goal that sizes everything

chock enforces in-agent on 4 chock agent names today — `claude` + `cursor` via
pre-tool-use, `copilot` + `vscode` via agent-hooks (`compile/surfaces.py:44-56`) — which
map to **3** agentseam vendors (`compile/levels.py:8-13`); agentseam adapts **12**
(`matrix.adapted_agents()` at the pin **[v]**). The design is therefore judged on what
vendors #5–#12 cost, not on cleaning up today's 4. The newly reachable set is **9**
(12 − 3): `antigravity`, `codex_cli` (today reachable only through its plugin store,
not the repo-level hook surface), `devin`, `gemini_cli`, `grok`, `junie` (absent from
chock entirely today **[v]**), `kimi_code`, `tabnine`, `windsurf`. The dispatch brief
said 8; the recount says 9, because `copilot`/`vscode` are one vendor and `junie` is
missing today.

Data literals are only ~8% of `src/chock` **[r]** — extraction is not the lever;
derivation is: the per-vendor bulk is five hand-written modules per vendor doing the
same three jobs with different words in them.

## 1. The derivation map

The full fact-by-fact audit — every per-vendor fact in `compile/emitters/`,
`hooks/installers.py`, `hooks/*_install.py` and `plugin/*.py`, classified DA
(derives-from-agentseam), SD (chock-store-data) or CC (chock-code) with file:line at
both pins, plus the nine facts recorded in BOTH repos today (two of them live
disagreements) — is split out by activity into
`derive-from-vendor-config-map.md` in this directory. Its conclusions this document
builds on:

- Wire facts (config paths, event names/spellings, hook-entry shapes, shell-tool
  vocabularies, envelopes) are all DA; chock re-records nine of them today, and in two
  places the repos *disagree* (VS Code `preToolUse` vs `PreToolUse` entry shape; cursor
  `failClosed`) — the drift class the derivation kills.
- Store layout already derives from `agentseam.packaging` bar two hardcoded
  `"scripts/{name}"` templates (`plugin/codex.py:31`, `plugin/cursor.py:32`) [v]; the
  three shared packager roles are AST-identical across the four stores with the store
  token normalized (162 lines) [v]; the two schema-bound roles differ 4-way (§5 here).
- What stays CC is policy, not vendor facts: guard-script conventions, timeout budget,
  interpreter discovery/baking, merge-and-ownership logic, the SessionStart arm,
  claude-managed fragments, fail-posture choices.

## 2. Target shape

```
src/chock/vendors.py          # NEW ~60 lines: loads vendor config + matrix; alias
                              #   table; derived enforcement set; nothing else
compile/emitters/in_agent.py  # NEW: one emitter; <agent>-hooks.json fragments from
                              #   hook_entry (replaces the two vendor emitters)
hooks/in_agent_install.py     # NEW: one installer (config_path + chock merge policy +
                              #   interpreter baking + ownership marker) replacing the
                              #   three; sessionstart_install stays (claude-only, CC)
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

## 3. Coverage honesty: grade = matrix row × per-claim basis × witness ledger

Amended per the owner's 2026-09-01 decision (org-plan, W36 brief amendment `4f8f1b8`):
D2's vendor entries will carry a **per-claim evidence entry** — `basis` from
`matrix_terms.BASES`, `date`, and the test id where a basis claims testing — keeping
**tested** (an automated fixture exercises the claim against agentseam's runtime)
distinct from **witnessed** (observed `live-run` in the vendor's real client). chock
consumes that; it never re-grades it.

### 3.1 The derivation

Membership: vendor V gets the in-agent surface iff `matrix.can_block(V, PRE_TOOL)` —
the predicate `surfaces.py:44-56` asserts today, made generative instead of a guarded
allowlist. A vendor whose row cannot block (`aider`, `replit`, raw `copilot`, `zed`
**[v]**) never gains an in-agent surface, no matter what any config file says: the
grading path reads capability from `agentseam.matrix` only, and per-claim evidence
from the vendor entry only as a **cap**, never as a source of capability — wire facts
and their evidence live in the vendor entry, the capability tier in the matrix
(DF §3.3), so no edit to either can widen a claim past the other's evidence.

The word: start from what `in_agent_level` computes today (`compile/levels.py:57-67`),
i.e. `matrix.enforcement_level(V, PRE_TOOL)`, lifted to `fail-to-ask` only when the
host is `best-effort` and the gate's `honours_ask` claim is **tested** (a fixture id in
its evidence entry — documented-only never earns the lift; deny-degrading hosts like
`codex_cli` never earn it at all). Then cap by evidence: the grade is
`min(matrix word, cap(weakest basis under the claims the grade rests on))`. The resting
claims for an in-agent grade: the matrix row itself, plus the vendor-entry claims
chock's wiring consumes — `config_path` is read, the hook entry fires, the pre-tool
grammar is spoken, the deny word lands. The binding basis is per-claim, not per-row:
one weak claim caps the cell even when the row's headline basis is strong.

Cap table (drawn here for owner review; the amendment fixes one anchor — `vendor-docs`
can never back an `enforced`-tier grade):

| weakest basis under the resting claims | max reportable word |
| :--- | :--- |
| `live-run` | `enforced` |
| `live-run-partial` | `enforceable` |
| `vendor-source`, `vendor-docs`, `third-party-install` | `best-effort` |
| `inherited` | `detect` — unreportable (`compile/levels.py:38`), surfaces as `none` **[h]** owner call |

**[h]** Whether `enforceable` should demand full `live-run`: only `cursor` is
affected (`live-run-partial`, `pre_tool` observed **[v]**), and the stricter line would
demote a word chock already publishes; this design keeps the line as drawn and flags it.

### 3.2 The witness ledger (chock-data, evidence-bearing)

Today chock's posture strings hand-assert witness ("witnessed blocking on Codex
Desktop, Windows, 2026-08-24", `plugin/codex.py:48-49`; same for cursor at
`plugin/cursor.py:51`) — chock's own live evidence about chock's own wiring, which
upstream evidence entries cannot carry. They move to one data table —
`data/witnesses.json` under `src/chock` (new in C1) — rows of
`{agent, surface, client, date, method}`, schema-validated (partial rows fail loud).
A "witnessed" posture template renders iff a ledger row exists for that
vendor × surface and the matrix row blocks; otherwise the unwitnessed template
("documented by the vendor; not witnessed by chock") renders. The ledger never moves
the word — it gates prose only.

Per-cell visibility (amendment requirement): each `coverage.json` cell becomes
`{"level": <word>, "basis": <binding basis>, "witnessed": bool}` and every rendered
report prints the pair — `best-effort (vendor-docs)` — so a strong word over weak
evidence cannot exist (the cap) and the evidence behind every word is one glance away
(the cell).

### 3.3 Consistency tests

All derivations with stated mutations, never presence checks (the chock#81 lesson):
(a) the derived in-agent set equals `{V : can_block(V, PRE_TOOL)}` recomputed from the
matrix in the test; (b) every "witnessed" phrase in emitted posture text maps to a
ledger row via the template engine — delete the row, the phrase must disappear;
(c) capability cannot enter from config: grade a synthetic vendor whose entry claims a
gate its matrix row denies, and assert the claim loses; (d) every vendor-entry claim
chock consumes carries an evidence entry — strip one basis from a fixture entry and the
loader must refuse it; (e) cap monotonicity: weaken any basis in a synthetic entry and
the grade must never rise, and must drop when it crosses a cap boundary.

### 3.4 Day one for the 9 new vendors, basis-capped [v]

Full table in the map, §M.6. Summary: all nine matrix words are `best-effort` and
every binding basis clears the `best-effort` cap, so no day-one *word* changes — every
day-one *cell* changes shape, to `best-effort (<basis>) · unwitnessed`. The cap's bite
is the future case: a fail-closed vendor documented only in `vendor-docs` surfaces as
`best-effort (vendor-docs)`, never `enforced`. One open row: if D2 records `tabnine`'s
vocabulary claim below `vendor-docs` (its decision words are `unverified` upstream),
that claim binds — owner decides whether it sinks below `best-effort` **[h]**. The
never-gain set and `cursor`'s `enforceable` (contingent on `failClosed`, map M.5(5))
are unchanged in the map table.

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
7. Renderer code changes **only** if X's manifest schema needs content-dependent
   branching the §5 renderer cannot express — a measured criterion, not a convenience
   door.

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
| C2 | wire facts → vendor-config reads (config paths, events, hook entries, tool lists); one emitter + one installer; settles map M.5(4) and M.5(5) with witness evidence recorded upstream | **D2 landed + released** (chock pins `agentseam==0.2.0` at `pyproject.toml:63`; a pin bump needs a release, freeze or not) | D3–D6 |
| C3 | derived `SURFACE_AGENTS` + in-agent extension to the 9 vendors; day-one coverage per §3.3; per-vendor golden fixtures for fragments and runtimes | C2; runtime bundles for new vendors work off today's `bundler.bundle` **[v]**, so D3–D6 are *not* blockers | D3–D6 |
| C4 | re-golden vendored runtimes against agentseam's engine-built bundles; byte-stability | D6 released | — |

Every C-wave lands green independently; C0/C1 are pure-chock refactors provable
byte-identical (C0) or prose-only (C1) by the existing goldens.

## 8. Test intent ledger

Survive re-targeted: the per-vendor suites (`test_claude_plugin.py`,
`test_cursor_codex_plugin.py`, `test_copilot_plugin.py`, `test_cursor_hooks.py`,
`test_agent_hooks.py`) become the store/installer conformance load over derived
output — none die. `test_coverage_is_derived.py`, `test_coverage_honesty*.py`,
`test_enforcement_matrix.py` extend to the derived agent set and the basis cell.

Must be written: (1) the five §3.3 consistency derivations with their stated mutations;
(2) store-data schema validation, unknown keys fatal; (3) golden wire fixtures per
vendor × surface captured **before** C2 flips any read (the empty-diff proof, agentseam
D1's trick applied to chock); (4) a thirteenth-vendor test: a synthetic vendor entry +
matrix row must yield surfaces, fragments, coverage and (with a synthetic store entry)
a package with zero chock code edits; (5) a legitimate-edit case per guard — a
rewrapped posture paragraph must still pass. These mutations failing is not a claim the
class is closed.

## 9. Open questions carried as hypotheses

- **[h]** map M.1: D2's schema needs a repo-root token field (`${CLAUDE_PROJECT_DIR}`
  analogue) and a `vscode_copilot` shell-tool list; chock is the evidence donor for
  both. If D2 refuses wire facts chock needs, chock carries a small overlay table —
  same schema, chock-owned rows, consistency-tested for disjointness — rather than
  forking entries.
- **[h]** §5's copilot extensions-block function is the only store code predicted to
  survive; if implementation finds a second store needing code, the renderer's data
  vocabulary is drawn too narrow — revisit the vocabulary, don't grow store modules.
- **[h]** Whether chock should set cursor's `failClosed: true` (map M.5(5)) is an
  enforcement-behaviour change with a real blast radius (a crashing guard starts
  blocking sessions); it needs an owner decision and a witnessed run, not a silent
  flag-flip during C2.
- **[h]** The 9 new vendors' guard runtimes assume agentseam's bundles speak each
  vendor's verdict grammar correctly under chock's `--guard` protocol
  (`gate/runtime_bundle.py:59-68` injects the same handler everywhere); windsurf's
  exit-code grammar (G5) is the case most likely to surprise — C3 must golden-test it
  first.
