- **The engine's time limits now always fire before the client's hook timeout, on every hook path.** A client's
  hook timeout fails OPEN (the command runs); chock's own limits ask a person or deny. One budget,
  `ENGINE_BUDGET_SECONDS` (30 s), is now shared by the guard, the write gate, tool-call scripts and script gates,
  and one hook invocation spends it once: the bash probes, `git status` and the gate runner each get what is
  left, where a turn's end could take 30 s of `git status` then 30 s of gate (60 s) against a 45 s client
  timeout. A `git status` that does not finish at Stop now refuses with a reason on stderr, instead of reading as
  a clean worktree and allowing. The emitted timeout is the budget plus a 15 s start-up margin (45 s), in each
  client's own unit, and now also reaches the in-agent entries of Antigravity, Codex, Devin, Gemini CLI (45000 ms),
  Grok and Tabnine (45000 ms), which carried no key and ran on the client's default (Grok 5 s, Antigravity 30 s,
  Gemini 60 s, Codex 600 s). Windsurf's documented hook entry has no timeout field, so it still runs on its own
  undocumented default. Plugin packages (Claude Code, Codex, Copilot, Cursor, Devin) always carried the key. Run
  `chock sync` to rewrite installed hook configs.
  A `git status` that fails for any other reason at Stop (exit 128 "dubious ownership", git missing from PATH) now
  refuses with that reason too, where it used to read as a clean worktree and allow; only "not a git repository"
  still reads as empty. Timeout messages now report the time the call was actually allowed, not the full budget.
