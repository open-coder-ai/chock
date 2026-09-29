# Gate DSL Reference

For `artifact: hook` policies, the gate is declared under `hook.gate` in `manifest.yaml`.
`chock compile` flattens it into `.chock/compiled/<id>/git-hook/gate.json`.

## `hook.gate` object

| field | required | type | notes |
|-------|----------|------|-------|
| `kind` | yes | string | `content_regex`, `forbidden_ref`, `dependency_allowlist`, `test_integrity`, `script`, or `egress_allowlist` (gateway-only) |
| `on` | yes | list | events: `commit`, `push`, `tool_use`. The key must be quoted `"on"` in YAML. |
| `action` | yes | string | `block`, `verify`, or `warn` |
| `message` | yes | string | printed to stderr when the gate blocks |
| `params` | yes | object | kind-specific parameters |

### `kind: content_regex`

| param | required | type | notes |
|-------|----------|------|-------|
| `content_pattern` | yes | string | regex matched against each line or the blob |
| `scan` | no | string | `added_lines` (default) or `staged_blob` |
| `forbidden_path_regex` | no | string | regex applied to staged file paths |
| `allowlist_pragma` | no | string | regex matched on lines/blobs; matching content is ignored at commit, push and ci. With `CHOCK_AGENT_COMMIT` set, only a waiver already in HEAD is honoured |

**At the mcp-gateway** (when `"on"` includes `tool_use`): the gate is emitted to the
`mcp-gateway` surface and evaluated against each `tools/call` argument string. Only
`content_pattern` applies there; `scan`, `forbidden_path_regex`, and `allowlist_pragma`
are git-diff concepts and are **not** honored by the gateway (the argument is live,
attacker-controlled text with no reviewer, so a match always blocks). A gate with no
`tool_use` in `"on"` is not emitted to the gateway at all.

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
| `allowlist_pragma` | no | string | regex matched on a line; a match on an added line skips that file's counting entirely; not honoured with `CHOCK_AGENT_COMMIT` set |

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
{"event": "tool_use", "repo_root": "/path/to/repo", "writes": {"src/App.java": "<file text>"}}
```

A compiled gate may carry `script_base: gate` beside `params`, which the runner reads as "the
script lives beside this gate file" instead of "under the repository root". Only a packaged
plugin writes it: there the gate, the runner and the script travel together and no repository
holds them.

`event` is `commit`, `push` or `tool_use`. `writes` is the staged blobs at `commit` and
`push`, and the write itself at `tool_use` -- the file a tool call is about to write, or what
the turn left on disk at its end -- so one script serves every surface, and it reaches the
write path and the turn's end exactly as `content_regex` does. The script answers with its
exit code: `0` allows; `1` refuses, with its own words on stderr, which become the reason
shown (the gate's `message` is not printed for a script that spoke). Any other outcome -- a
missing script, a crash, a timeout (30s) -- refuses too, in the runner's words: a gate that
reaches no decision never reports an allow it never established.

`chock compile` rewrites `script` to the file's path from the repository root, which is all
the runner has; the ambient line an agent reads keeps the bare name, so the packaged `SKILL.md`
is the same wherever the policy sits. `chock check` refuses a name that is not a bare `.py` file
name, and a script the policy does not ship. The script is deterministic code under
`implementations/`, so SEC-2 applies to it as to any guard, and `chock check --only evals`
copies that directory into the throwaway repository a staged-files case is replayed in, where
the compiled gate names it.

## Runtime note

The emitted git-hook shim probes for a working Python 3 interpreter in the order `python3`, `python`, `py` and then calls `.chock/bin/gate.py`. This makes enforcement work on stock Windows as well as POSIX without `pip install`.
