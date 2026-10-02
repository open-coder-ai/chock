- **The write-path door of a shell guard or an event script is declared and validated (DET-6).**
  `hook.script` runs only from the git hook, so it keeps its `commit`/`push`/`commit-msg` events;
  the Edit/Write door is a `hook.gate` with `tool_use` in `on` -- `kind: script` for logic, or a
  path gate (`content_regex`, `forbidden_path_regex`, `content_pattern: '(?!)'`) as
  protect-agent-config ships. New `manifest_write_path` errors: a `hook.script` event outside the
  git events (the message names both gate forms), a `'(?!)'` gate with no path (it can never
  refuse), and a guard's path gate without `tool_use`. The validator no longer crashes with a
  `KeyError` on `hook.script.on: [tool_use]`. Schema descriptions and `spec/script-backed-gates.md`
  state the pairing.
