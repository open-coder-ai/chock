# Derivation map: chock's per-vendor facts and their sources of truth

Companion audit for `derive-from-vendor-config.md` (same pins: chock `bb25bbe`,
agentseam `427fc26`; same [v]/[r]/[h] legend; the DA/SD/CC vocabulary is defined below). Every per-vendor fact in `compile/emitters/`, `hooks/installers.py`,
`hooks/*_install.py` and `plugin/*.py`, with its source of truth once agentseam's
vendor config exists.

## The classification

Source-of-truth vocabulary:

- **DA** — derives from agentseam: the vendor config entry (DF §3.2: `config_path`,
  `events`/`wire_events`, `hook_entry`, `tools`, `verdicts.gates`), the capability
  matrix (`matrix.py`), or `packaging.py`. chock reads it; chock never re-records it.
- **SD** — chock-store-data: marketplace manifest schema facts per store; lives in a
  chock data table because agentseam has no marketplace concept.
- **CC** — chock-code: policy logic that stays code (the line of DF §3.1 applies
  unchanged: word/key/flag/list-order is data; branching is code).

### M.1 `compile/emitters/`

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
| VS Code entry keys `type/matcher/timeout/timeoutSec/bash/command/powershell/windows` | `agent_hooks.py:45-54` | DA | `hook_entry` `entry_extra`; **divergence** — agentseam emits `{type, command, windows}` (`adapters/vscode_copilot.py:185-193`); see M.5(4) |
| Claude managed-settings fragment schema | `claude_managed.py:14-40` | CC | claude-only surface, policy-conditional content; no config equivalent upstream |
| `ambient` / `ci` / `git_hook` / `mcp_gateway` emitters | whole files | CC | agent-agnostic **[v]** (no vendor token in any of them) |

### M.2 `hooks/installers.py`, `hooks/*_install.py`

| fact | today | class | source |
| :--- | :--- | :--- | :--- |
| git dispatcher/validate-hook machinery | `installers.py` (whole file) | CC | vendor-free **[v]** |
| `.claude/settings.json` | `pretooluse_install.py:14` | DA | `config_path` (agentseam `adapters/claude_code.py:181`) — duplicated in both repos today |
| `.cursor/hooks.json` | `cursor_install.py:18` | DA | `config_path` (agentseam `adapters/cursor.py:231`) — duplicated |
| `.github/hooks/` directory | `agenthooks_install.py:11` | DA | dirname of `vscode_copilot` `config_path` (agentseam `adapters/vscode_copilot.py:196`); the `chock.json` filename stays CC (chock owns its own file beside `agentseam.json`) |
| event key `preToolUse` | `agenthooks_install.py:42` | DA | `wire_events`; **divergence** — agentseam spells it `PreToolUse`; see M.5(4) |
| `version: 1` envelope (cursor) | `cursor_install.py:78` | DA | cursor `hook_config` envelope (agentseam `adapters/cursor.py:228`) |
| ownership markers `/.chock/bin/<agent>.py` | `pretooluse_install.py:16`, `cursor_install.py:20`, `sessionstart_install.py:20` | CC | derived from agent id; the marker convention is chock's |
| interpreter baking / normalize / keep-if-runs merge logic | `pretooluse_install.py:21-59,105-130` | CC | chock policy, shared verbatim by all installers already **[v]** (`cursor_install.py:11-15` imports it) |
| SessionStart arm fragment + orchestration | `sessionstart_install.py:22-30`, `gate/runtime_bundle.py:71-106` | CC | claude-only chock behaviour; event name + shape from config, the branch stays code |
| `RUNTIME_FILENAME` map | `runtime_vendor.py:9-13` | CC | delete: it is `f"{agent}.py"` for all three rows **[v]** |
| `RUNTIME_AGENTS` tuple | `gate/runtime_bundle.py:17` | DA | derive: adapted vendors chock wires in-agent (main doc §3); `render()` itself is already agent-generic **[v]** (`runtime_bundle.py:123-135` wraps `bundler.bundle(agent)`) |
| `VENDORED_RUNTIMES` bundle rows | `vendored.py:9-11` | DA | same derivation |
| per-vendor installer wiring in `hooks/install.py:67-95` | three copied try/except blocks | CC→one loop | one generic installer over the derived vendor set |

### M.3 name maps, surfaces, coverage

| fact | today | class | source |
| :--- | :--- | :--- | :--- |
| `MATRIX_AGENT` (4 rows) | `compile/levels.py:8-13` | DA | delete; one alias table (chock name ↔ agentseam id) is data, everything else uses agentseam ids |
| `CHOCK_AGENT` (14 rows) | `scaffold/adapters.py:14-29` | DA | the same single alias table; today it and `MATRIX_AGENT` are two hand-kept maps that can drift from each other **[v]** |
| `SURFACE_AGENTS` (14 hand-rows) | `compile/surfaces.py:21-41` | DA | derive: every matrix agent gets `{ambient, git-hook, ci-gate}`; in-agent membership per main doc §3. `aider`/`replit` (tier `none`/`unadapted` **[v]**) stay advisory-only automatically; `junie` appears automatically |
| in-agent membership assertion | `compile/surfaces.py:44-56` | DA | subsumed by the main-doc §3 derivation + consistency test |
| `installed_for` / `agent_hooks_for` dicts | `compile/compiler.py:129-133` | DA | one generic `installed_policy_ids(vendor)` over the derived set |
| in-agent level words | `compile/levels.py:57-67` | DA (already) | unchanged: `matrix.enforcement_level` is already the source **[v]**; gains `honours_ask` from `verdicts.gates` (main doc §3.2) |

### M.4 `plugin/*.py` (the four store packagers)

Recount of the orchestrator's measurement, method: per store, extract the five role
functions, normalize the store token, strip docstrings, hash
`ast.dump(include_attributes=False)` **[v]**:

| role | distinct / 4 | lines (4 stores) | class |
| :--- | :--- | :--- | :--- |
| `stale_<store>_files` | 1 | 48 | CC — one parametrized function; `OWNED_SUBTREES` becomes store data (`claude.py:121`, `codex.py:146`, `cursor.py:137`, `copilot.py:117`) |
| `build_<store>_plugin` | 1 | 62 | CC — one function |
| `<store>_plugin_differences` | 1 | 52 | CC — one function |
| `build_<store>_manifest` | 4 | 85 | SD + renderer — main doc §5 |
| `<store>_plugin_files` | 4 | 154 | SD + DA + renderer — main doc §5 |

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
| posture strings (enforced/advisory, witness claims) | `claude.py:29-42`, `codex.py:46-64`, `cursor.py:48-63`, `copilot.py:31-50` | SD + main doc §3 | templates in store data; the *witness* clauses fill from the ledger (main doc §3.3), never hand-asserted |
| `COPILOT_NAMESPACE`, `NAMESPACE`, `SCHEMA_URL`, name grammar | `copilot.py:27`, `build.py:15-48` | SD | store schema data |
| guarded hook command (unresolved root ⇒ allow) | `copilot.py:53-59` | CC | fail-posture policy + DA `plugin_root` token |
| marketplace tree manifests | `marketplace.py:16-32` | DA | `packaging.layout(agent)["manifest"]` — duplicated verbatim in both repos today **[v]** (`marketplace.py:18` = packaging's `claude_code` manifest path) |
| marketplace index styles, lockfile, catalog page | `marketplace.py:56-157` | SD/CC | store data (index style) + chock code |

### M.5 The drift class this kills — facts recorded in BOTH repos today [v]

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
   no agentseam counterpart yet (gap, M.1).
7. Hook entry shapes: `{matcher, hooks:[{type,command,timeout}]}`
   (`claude_pretooluse.py:55-64`, `plugin/claude.py:103-113`, `plugin/codex.py:128-137`,
   `plugin/copilot.py:99-108`) ≡ agentseam `adapters/_common.py:9-20`.
8. Store manifest paths: `plugin/marketplace.py:18,23,28` ≡ `packaging.layout(...)`
   entries chock already imports two files away.
9. Windows powershell wrapping: `compile/emitters/agent_hooks.py:23-31` vs agentseam
   `adapters/_windows.py`.

