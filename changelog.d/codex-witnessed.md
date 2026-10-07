- **Codex is witnessed: `chock install --selection --client codex` no longer warns "Untested".** An install in
  Codex CLI 0.157.1 on Windows was witnessed (guard, write gate, turn-end gate, self-protection and per-policy
  on/off), so the `client` warning that chock has not witnessed an install now names only Copilot, Cursor and
  Devin. Codex still warns that its plugin hooks stay advisory until trusted in `/hooks`.
