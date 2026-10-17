- **Antigravity: hooks.json now uses the documented schema, so Antigravity loads chock's hooks.**
  Antigravity rejected the plugin's hooks.json (`invalid hook "agentseam": command hook must specify
  'command'`, a maintainer's witness run, 2026-10-17) because Stop was written as a `{hooks}` group.
  agentseam is pinned to main 945ceb0, which writes Stop handlers bare (`{type, command}`) and gives every
  PreToolUse/PostToolUse group `matcher: "*"`, per antigravity.google/docs/hooks (read 2026-10-17). Both the
  plugin's hooks.json and `chock sync`'s `.agents/hooks.json` follow. Not witnessed yet: the corrected file
  has not been run in Antigravity.
