- **`chock install --selection` builds for any of the five agents: selection schema 2 and `--client`.**
  `selection.schema.json` now defines schema 2: `client` (claude-code, cursor, codex, copilot, devin),
  `bundle: {name (default chock-guardrails), version}`, and entries `{from: catalog, id, version, sha256}` or
  `{from: local, id, path}`. A local entry is valid in the schema but refused at install as not yet supported.
  Schema 1 is still read and is mapped to schema 2 (bundle `chock-guardrails` 1.0.0, same version digest).
  `--client` overrides the selection's client. Each client has its own default folder
  (`~/.chock/marketplace/<client>`; Cursor `~/.cursor/plugins/local/<bundle.name>`), its own layout
  (a marketplace for Claude Code, Copilot and Codex; a plugin folder for Cursor and Devin), its own index (Codex:
  `.agents/plugins/marketplace.json`), its own steps (`--apply` runs only the client's commands, only when its
  binary is on PATH, and never edits a client's settings), label qualifiers (Codex: until its hooks are trusted;
  Devin: best-effort, fails open; Copilot and Devin: a gate judges at turn end only) and `client` warnings. Only
  Claude Code has been witnessed; the others are labelled untested. The plugin's name is `bundle.name` and its
  version `<bundle.version>+<digest12>`, so several bundles coexist per client, a second client never replaces
  the first, and install warns when a picked policy is already in another chock plugin for that client.
- **Breaking: the `bundles.yaml` route is retired.** `chock plugin build` no longer reads `bundles.yaml` or
  takes `--bundles`, writes no `chock-bundles.json`, and Claude bundles are no longer a `dependencies`
  meta-plugin: a bundle is a selection, built as one merged plugin by `chock install --selection`. Per-policy
  `chock plugin build` output is unchanged; a previously built bundle directory under `--out-dir` is now stale.
