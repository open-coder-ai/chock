- `chock emit --managed claude_code --python <absolute path> --on-failure block|allow --out <dir>`
  (preview) writes, under `<dir>/claude_code/` and nowhere else, a Claude Code managed-settings
  drop-in (`managed-settings.d/50-chock.json`), the hook bundle it runs (`bundle/<policy>/scripts/`:
  runtime, guard or gate), `deploy.json` (where an admin places each part, what every machine needs,
  what the `--on-failure` choice does, what it does not promise, the undo step) and `labels.json`.
  Every hook is exec form: it starts the `--python` interpreter directly, so no shell, PATH lookup
  or git config picks it. `--on-failure` has no default: `block` sets `onFailure: "block"` on the
  `PreToolUse` hooks and refuses a matched call when the interpreter or a bundle file is missing;
  `allow` sets neither and lets the call through with a note. The repository stop's every-tool
  entry is not emitted. The command refuses an `--out` that is a filesystem root or resolves into
  a system folder (any spelling, case-insensitive on macOS and Windows), names a file, or already
  holds `claude_code/`; it elevates nothing and deploys nothing. `--lock` adds
  `allowManagedHooksOnly` (off by default; `deploy.json` lists every effect the vendor documents);
  `allowManagedPermissionRulesOnly` is never emitted. Every label is `best-effort (vendor-docs)`,
  unwitnessed, until a `managed` witness row exists. A local administrator can still edit or remove
  the file. Native `permissions.deny` rules are not emitted yet.
- `chock compile` no longer writes `managed-setting/managed-settings.json`: that file used a shape
  Claude Code does not read.
- Every child interpreter a hook runtime starts (a Python guard, the gate runner, a script gate) now
  runs isolated (`-I`), with its own folder put on the import path explicitly and every `PYTHON*`
  variable removed from its environment, on every route. The hook launcher (`launch.sh`) starts a
  runtime script with `-E -s`, so no `PYTHON*` variable or user site reaches the outer interpreter
  either (its `-m chock` form keeps the environment: it needs the installed package). A hostile `PYTHONPATH`, `PYTHONHOME`,
  `PYTHONPLATLIBDIR` or `PYTHONSAFEPATH` no longer lets a refused command through or turns a refusal
  into a prompt.
- `chock emit --managed claude_code`: the bootstrap now checks every bundled file, so a missing guard
  or `chock_shellparse` follows `--on-failure` like any other missing file. `deploy.json` gains
  `stop_files` (the repository's `.chock/stop.json` and the `~/.chock/stops/` files, each with its
  effect), `client_versions` (2.1.295 for `onFailure`, 2.1.314 for Monitor commands, each quoted with
  the date read) and `not_covered`.
