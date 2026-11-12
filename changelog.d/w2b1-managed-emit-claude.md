- `chock emit --managed claude_code --out <dir>` (preview) writes, under `<dir>/claude_code/` and
  nowhere else, a Claude Code managed-settings drop-in (`managed-settings.d/50-chock.json`), the
  self-contained hook bundle it runs (`bundle/<policy>/scripts/`: launcher, runtime, guard or gate),
  `deploy.json` (where an admin places each part, what every machine needs, what it does not
  promise, the undo step) and `labels.json`. It refuses an `--out` that resolves inside a system
  path, never writes into an existing `<dir>/claude_code`, elevates nothing and deploys nothing.
  Hook commands name the bundle by absolute path (`--deploy-root`, default the vendor's admin
  folder + `/chock`); every `PreToolUse` hook carries `onFailure: "block"` and a 45 s timeout.
  `--lock` adds `allowManagedHooksOnly` (off by default: it stops every other hook on the machine);
  `allowManagedPermissionRulesOnly` is never emitted. Every label is `best-effort (vendor-docs)`,
  unwitnessed, until a `managed` witness row exists. A local administrator can still edit or
  remove the file. Native `permissions.deny` rules are not emitted yet.
- `chock compile` no longer writes `managed-setting/managed-settings.json`: that file used a shape
  Claude Code does not read.
