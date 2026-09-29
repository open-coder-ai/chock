# Gate DSL Reference

For `artifact: hook` policies, and for `artifact: rule` policies that keep their rule text, the gate
is declared under `hook.gate` in `manifest.yaml`. A hook may also carry a `hook.script`
(`spec/script-backed-gates.md`) beside it, provided the two do not both run at one git event.
`chock compile` flattens it into `.chock/compiled/<id>/git-hook/gate.json`.

## `hook.gate` object

| field | required | type | notes |
|-------|----------|------|-------|
| `kind` | yes | string | `content_regex`, `forbidden_ref`, `dependency_allowlist`, `test_integrity`, `script`, or `egress_allowlist` (gateway-only) |
| `on` | yes | list | events: `commit`, `push`, `tool_use`, `tool_call`. The key must be quoted `"on"` in YAML. |
| `action` | no | string | `block` (default), `ask`, or `warn`: what a violation does, see [Actions](#actions). `verify` is a value of `enforcement`, not of `action`, and is refused |
| `message` | yes | string | the reason: printed to stderr when the gate blocks, asks or warns |
| `params` | yes | object | kind-specific parameters |
| `outside_repo` | no | list | globs of files outside the repository whose writes this gate may judge (see [Writes outside the repository](#writes-outside-the-repository)); needs `tool_use` in `on` |

## Actions

`action` is what the runner does with a violation. It never changes what counts as one.

| surface | `block` | `ask` | `warn` |
|---------|---------|-------|--------|
| `commit`, `push` | refuse, exit 1 | refuse, exit 1, unless `CHOCK_ALLOW` names the policy and the command is not an agent's (below) | reason on stderr, exit 0 |
| `ci` | fail, exit 1 | `::warning title=chock <id>::<reason>` annotation, exit 0 | the same annotation, exit 0 |
| `tool_use`, at PreToolUse | deny | ask the person: `permissionDecision: ask` with the reason, on vendors that honour an ask; every other vendor denies | allow; Claude Code gets the reason as PreToolUse `additionalContext` (no `permissionDecision`, so the user's own permission prompt is untouched); every other vendor gets stderr and the gate log only, as none has a verified channel |
| `tool_use`, at Stop | block | a warning: nobody can be asked at the turn's end | a warning: Claude Code shows the reason to the user as `systemMessage`; never a block |
| mcp-gateway | error to the client | block: a proxy has no person to ask | pass through, reason on stderr |

Every outcome is a record in the gate log: `verdict` is `allow`, `block`, `ask` or `warn`, and an
`ask` a person answered is `allow` with `override: CHOCK_ALLOW`.

**Exit codes of `gate.py run`.** `0` allow (a warn at a git event or ci is an allow), `1` refuse,
`2` the gate could not judge. At the agent events (`--event pre-tool-use|stop`) two more, the
command-guard contract's own: `3` ask and `4` warn, which the vendored runtimes turn into their
vendor's dialect. `gate.py script-verdict --policy <id> --event <hook> --exit 3|4` settles a
script-backed hook's ask or warn the same way (see `spec/script-backed-gates.md`).

**`ask` at a hook.** A hook cannot prompt, so an ask refuses until a person answers out of band:
`CHOCK_ALLOW=<policy-id>[,<policy-id>...]` in the environment of that one command, and the
command is not an agent's. The ids are exact (no wildcard), `CHOCK_ALLOW` overrides nothing but
an `ask`, and an agent commit ignores it. A refusal prints the reason, then the override to run.

**Agent commits.** A commit or push is an agent's when `CHOCK_AGENT_COMMIT` is truthy, or
`CLAUDECODE=1`, or `AI_AGENT` is non-empty, or any variable named under `agent_commit_env:` in
`.chock/config.yaml` is non-empty. `CHOCK_AGENT_COMMIT` set to `0`, `false`, `no` or `off` says
"a person" and wins over every marker: the escape hatch for a person running git in an agent's
terminal. An agent can set it too: the marker is a default, not an authenticated identity, and
`CHOCK_ALLOW` is typed as easily. What backs them is the separate guards on an agent's own
commands and review, not the hook. A person answering an `ask` in an agent's terminal is told to
set both variables. An agent commit is judged at the event `agent-commit`: a
waiver it adds is not honoured. Only Claude Code's markers are witnessed (a git hook run by the
Bash tool saw both, `src/chock/data/witnesses.json`, surface `git-hook-env`); Codex, Cursor and
Copilot markers are unverified and are added per repository under `agent_commit_env:`.

```yaml
# .chock/config.yaml
agent_commit_env: [CODEX_SANDBOX, CURSOR_TRACE_ID]   # or a block list of `- NAME` lines
```

The runner is stdlib-only and reads only that key, only as an inline list, one name, or a block
list; anything else names no variable.

**Coverage.** A policy whose only mechanism warns is not credited as enforcing: the gate's
`git-hook`, `ci-gate`, `stop`, `pre-tool-use` and `agent-hooks` surfaces are withheld, so its
grade is what it also ships (an ambient rule reads `advisory`). An `ask` counts: a person decides,
and at a hook that is a refusal until they do. A shell guard shipped beside a warn gate keeps its own
pre-tool credit.

### `kind: content_regex`

| param | required | type | notes |
|-------|----------|------|-------|
| `content_pattern` | yes | string | regex matched against each line or the blob |
| `scan` | no | string | `added_lines` (default) or `staged_blob` |
| `forbidden_path_regex` | no | string | regex applied to staged file paths |
| `allowlist_pragma` | no | string | regex matched on lines/blobs; matching content is ignored at commit, push and ci. On an agent commit (see [Actions](#actions)), and at `tool_use`, only a waiver already in HEAD is honoured |

**At the mcp-gateway** (when `"on"` includes `tool_use`): the gate is emitted to the
`mcp-gateway` surface and evaluated against each `tools/call` argument string. Only
`content_pattern` applies there; `scan`, `forbidden_path_regex`, and `allowlist_pragma`
are git-diff concepts and are **not** honored by the gateway (the argument is live,
attacker-controlled text with no reviewer, so a match always blocks). A gate with no
`tool_use` in `"on"` is not emitted to the gateway at all.

**In the agent** (`"on"` includes `tool_use`): the gate runs at PreToolUse on a write (the
file as it would be after it) and at Stop (what the turn left on disk). `content_regex`,
`script`, `dependency_allowlist` and `test_integrity` run there; `forbidden_ref` cannot (no branch
in a tool call) and refuses. Each kind reads the change against a baseline: at PreToolUse the file
on disk before the write, at Stop `HEAD` (absent in HEAD: every line is new). `added_lines` is an
edit's own text, else the diff against that baseline, so lines already there -- a whole-file
Write's unchanged lines, an old violation in a touched file -- are never scanned (`scan:
staged_blob` still reads the whole file). `allowlist_pragma` is honoured at `tool_use` only on a
line already in HEAD; a waiver the write or turn adds is not.

### Event `tool_call`: a gate by tool name

`"on": [tool_call]` runs the gate at **PreToolUse for any tool**, chosen by tool name. It needs
`params.tools`: a list of globs over the tool's name (`*` any run, `?` one character, names
case-sensitive and matched whole): `mcp__Firecrawl__*`, `WebFetch`, `mcp__*`. Only `content_regex`
and `script` can judge a call (a call carries no file and no branch); `chock check` refuses the
others, a `tool_call` gate with no `tools`, and `tools` without `tool_call`. A script speaks the
same exit codes as at every other event (`0` allow, `1` block, `3` ask, `4` warn), and the gate's
`action` is a ceiling on what it and any refusal can do, as in [Actions](#actions).

| kind | reads | verdict |
|------|-------|---------|
| `content_regex` | `content_pattern` searched in the tool input serialised as JSON (sorted keys, non-ASCII kept). `scan`, `forbidden_path_regex` and `allowlist_pragma` do not apply, and no waiver is honoured: the input is live text | a match blocks, with the gate's `message` |
| `script` | JSON on stdin: `{"event": "tool_call", "repo_root": "...", "tool": "<name>", "input": {<tool input>}, "session": {"id", "log_path", "tool_use_id"}}` | exit `0` allows, `1` blocks, `3` asks, `4` warns, each with the script's stderr; anything else (crash, timeout, missing script) takes the declared `action` |

`session` is the handle to the per-session log ([`session-log.md`](session-log.md)); the helper
the vendored helper `chock_session.py` reads it. A `script` gate's hook is installed with no matcher, so it
sees every tool call and the log is complete; the runtime applies the tool globs.

The gate runs in the agent only, on the vendors that record a tool vocabulary in their vendor
facts: Claude Code, Codex CLI, Cursor, Gemini CLI, and VS Code Copilot Chat / Copilot CLI (chock's
own hooks file, whose `PreToolUse` was witnessed). Claude Code, Codex and Gemini get a matcher
(`^(?:glob|glob)$`) for a `content_regex` gate; Cursor and Copilot record no matcher semantics, so
their entry has none and the runtime filters. Antigravity, Devin, Grok, Tabnine and Windsurf record
no tool vocabulary and get no `tool_call` entry; a policy reads as installed there only through its
other surfaces, so coverage never credits `tool_call` where it is not emitted. It is not evaluated
at the mcp-gateway, at commit, or at Stop.

### Writes outside the repository

A write gate judges repo-relative paths. A gate that declares `outside_repo` also receives writes
whose path lies outside the repository, but only those matching one of its globs; every other
outside write stays ignored. Globs are absolute or start with `~` (`~/.claude/memory/*`,
`C:\Users\*\.claude\memory\*`), `~` is expanded when the hook runs, and on Windows backslashes,
drive letters and letter case compare the way Windows does. A matching write reaches the gate under
its absolute, slash-separated path (a `script` gate finds it as a key of `writes`; `applies_to.paths`
does not filter it, as those globs are repo-relative), judged against the file on disk as its
baseline.

**PreToolUse only.** The Stop hook reads the worktree through git, which cannot see a file outside
the repository, so an outside write is judged before it happens or not at all. A write made by a
shell command (`echo > ~/x`) carries no file argument and is not seen.

### `kind: forbidden_ref`

| param | required | type | notes |
|-------|----------|------|-------|
| `refs` | yes* | list | branch names like `main`, `master`; required unless resolved from `config_key` |
| `config_key` | no | string | dot-separated key into `.chock/config.yaml` whose list value supplies `refs` |

On `commit` the current branch is checked; on `push` the pushed refs from `stdin` are checked.

### `kind: egress_allowlist`

Gateway-only: evaluated by the mcp-gateway proxy against MCP tool-call arguments; it has
no commit/push runtime, so `"on"` must not list commit or push (validated).

| param | required | type | notes |
|-------|----------|------|-------|
| `allowed_hosts` | yes | list | hostnames; a listed host also allows its subdomains |

Host detection is scheme-agnostic (any `scheme://host`, scheme-relative `//host`) and also
recognizes a string argument that is *itself* a bare endpoint (`evil.io/x`, `127.0.0.1:8000`,
`[::1]:8000`, `localhost:8000`), across the raw and percent-decoded text, with userinfo and
FQDN root-dot normalized. An empty or stripped allowlist fails closed.

Best-effort by design: this is regex-based host extraction over free-form tool arguments,
not a full URL parser. Known gaps include IDN/punycode and alternate IP encodings (decimal
or octal IPv4). Treat it as friction on an MCP fetch/egress tool, not an airtight boundary
— pair it with a network-level control where the threat model requires one.

### `kind: dependency_allowlist`

| param | required | type | notes |
|-------|----------|------|-------|
| `manifests` | yes | list | which manifest formats to watch; each entry must be one of `requirements.txt`, `pyproject.toml`, `package.json`, `go.mod` |
| `allowlist_file` | yes | string | path to a line-delimited allowlist of dependency names |

Each format has a dedicated extractor that parses the **whole staged file**, so section
context is available:

| format | source of names |
|--------|-----------------|
| `requirements.txt` | one requirement per line; `#` comments and `-` options ignored |
| `pyproject.toml` | `project.dependencies`, `project.optional-dependencies`, `tool.poetry.dependencies` (excluding `python`) |
| `package.json` | `dependencies`, `devDependencies`, `peerDependencies`, `optionalDependencies` — metadata keys such as `name` and `scripts` are not dependencies |
| `go.mod` | `require` blocks and single-line `require` directives |

Only dependencies this commit **adds** are checked: the staged file's names minus the
`HEAD` version's names. Touching a manifest that already contains an unlisted package does
not block the commit. A manifest with no committed version is treated as all-new.

A format with no extractor is rejected by `chock check`, so a policy cannot claim
a format the runtime would silently ignore. A file that fails to parse yields no names —
a parse error is never converted into a block.

Extracted names are lowercased and compared against a lowercased allowlist.

### `kind: test_integrity`

| param | required | type | notes |
|-------|----------|------|-------|
| `test_path_regex` | yes | string | regex matched against staged paths to identify test files |
| `assertion_pattern` | yes | string | regex matched against a line to count it as an assertion |
| `dummy_assertion_pattern` | no | string | regex for a vacuous assertion (`assert True`, `expect(true)`); matched only on added lines |
| `allowlist_pragma` | no | string | regex matched on a line; a match on an added line skips that file's counting entirely; on an agent commit and at `tool_use`, only a waiver already in HEAD is honoured |

Blocks three shapes of a change that wins green CI by weakening the tests rather than
fixing the code: a deleted test file, a **net** loss of assertions across the whole
change (removed lines matching `assertion_pattern` outnumber added ones, counted only in
files matching `test_path_regex`), and a vacuous assertion added in place of a real one.
Only the staged diff is read (`removed_lines`/`added_lines`), so a file that already
contained fewer assertions before this commit does not block it.

### `kind: script`

| param | required | type | notes |
|-------|----------|------|-------|
| `script` | yes | string | a file name under the policy's `implementations/` directory: bare (no `/`, so nothing outside that directory) and `.py`, run by the runner's own interpreter |

For a check no declarative kind can hold -- one that has to parse, follow a value through a
method body, or read a rule table too large for `params`. The runner hands the policy's own
program the same material every kind above reads, as JSON on stdin:

```json
{"event": "tool_use", "repo_root": "/path/to/repo", "writes": {"src/App.java": "<file text>"}, "session": {"id": "s1", "log_path": "/path/to/repo/.chock/state/s1.jsonl", "tool_use_id": null}}
```

A compiled gate may carry `script_base: gate` beside `params`, which the runner reads as "the
script lives beside this gate file" instead of "under the repository root". Only a packaged
plugin writes it: there the gate, the runner and the script travel together and no repository
holds them.

`event` is `commit`, `push`, `tool_use` or (see above) `tool_call`. `session` is present only at the agent events. `writes` is the staged blobs at `commit` and
`push`, and the write itself at `tool_use` -- the file a tool call is about to write, or what
the turn left on disk at its end -- so one script serves every surface, and it reaches the
write path and the turn's end exactly as `content_regex` does. The script answers with its
exit code: `0` allows; `1` refuses, `3` asks, `4` warns, each with its own words on stderr, which
become the reason shown (the gate's `message` is not printed for a script that spoke). The
declared `action` is a ceiling: a script may choose a gentler verdict than the gate declares, never
a harsher one (`block` + exit 4 warns; `warn` + exit 1 or 3 warns; `ask` + exit 1 asks). Any other
outcome -- a missing script, an exit 1 with no words or with a crash signature (`Traceback`,
`syntax error`, `SyntaxError`, `unexpected EOF`), any other exit code, a timeout (30s) -- is
undecided, and an undecided gate takes its declared action in the runner's words: `block`
refuses, `ask` asks, `warn` warns. A gate that reaches no decision never reports an allow it never
established. `3` and `0`/`1` are the command-guard contract's; `4` exists only for script gates
and script-backed hooks (a command guard's exit 4 is still "not checked").

`chock compile` rewrites `script` to the file's path from the repository root, which is all
the runner has; the ambient line an agent reads keeps the bare name, so the packaged `SKILL.md`
is the same wherever the policy sits. `chock check` refuses a name that is not a bare `.py` file
name, and a script the policy does not ship. The script is deterministic code under
`implementations/`, so SEC-2 applies to it as to any guard, and `chock check --only evals`
copies that directory into the throwaway repository a staged-files case is replayed in, where
the compiled gate names it.

## Runtime note

The emitted git-hook shim probes for a working Python 3 interpreter in the order `python3`, `python`, `py` and then calls `.chock/bin/gate.py`. This makes enforcement work on stock Windows as well as POSIX without `pip install`.
