- **A client's hook timeout can no longer fire before chock's own guard timer.** Emitted hook configs
  (Claude Code, Codex, Cursor, Copilot, Devin and the other hooks-map clients) set `timeout` to 30 s, equal to
  the guard's 30 s timer, which starts only after interpreter start-up. The client's timeout could fire first,
  and a client hook timeout fails OPEN (the command runs), whereas the guard's own timeout asks a person. The
  emitted timeout is now the guard budget plus a 15 s start-up margin (45 s), derived from one constant. Run
  `chock sync` to rewrite installed hook configs. Clients whose entry carries no
  `timeout` key (Windsurf, Grok, Tabnine, Gemini, Antigravity) still run on the client's own default.
