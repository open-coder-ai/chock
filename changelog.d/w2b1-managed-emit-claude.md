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
