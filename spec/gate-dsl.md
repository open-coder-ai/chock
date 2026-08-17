# Gate DSL Reference

For `artifact: hook` policies, the gate is declared under `hook.gate` in `manifest.yaml`.
`chock compile` flattens it into `.chock/compiled/<id>/git-hook/gate.json`.

## `hook.gate` object

| field | required | type | notes |
|-------|----------|------|-------|
| `kind` | yes | string | `content_regex`, `forbidden_ref`, or `dependency_allowlist` |
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
| `allowlist_pragma` | no | string | regex matched on lines/blobs; matching content is ignored |

### `kind: forbidden_ref`

| param | required | type | notes |
|-------|----------|------|-------|
| `refs` | yes* | list | branch names like `main`, `master`; required unless resolved from `config_key` |
| `config_key` | no | string | dot-separated key into `.chock/config.yaml` whose list value supplies `refs` |

On `commit` the current branch is checked; on `push` the pushed refs from `stdin` are checked.

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

## Runtime note

The emitted git-hook shim probes for a working Python 3 interpreter in the order `python3`, `python`, `py` and then calls `.chock/bin/gate.py`. This makes enforcement work on stock Windows as well as POSIX without `pip install`.
