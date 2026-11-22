- `chock init` and `chock sync` add `.claude/settings.local.json` to the repo's `.gitignore` (and to an existing
  `.dockerignore`) when it targets Claude Code: Claude Code saves approved commands there, secrets included. A
  tracked copy is not touched; the two commands to untrack it are printed.
