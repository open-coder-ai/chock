- **Hardening: an `off` in `.chock/guardrails.json` or `~/.chock/guardrails.json` is honoured only by a session that
  started after that file's record last changed.** A merged plugin binds each session, by the session id the session
  log keeps (else the conversation id), to the toggle files and records it first sees; if one changes during the
  session, every member stays on for the rest of it with a one-line warning, and the change applies from the next
  session. Where the client documents a session-start event, the plugin's session-start hook binds the session and
  lists every member that is off, by scope; a compaction does not rebind. The Stop-time check also refuses a turn's
  end while a file changed during the session switches a member off. A client that sends no session id honours an
  `off` only after a session start. The built-in protect member stays non-toggleable. docs/custom-policies.md and the
  "customize guardrails" skill state that a toggle is not a security boundary against an agent running as the person.
  The built-in protection also refuses an agent's write to a session's binding (`guardrails-session-*.json` under
  `.chock/state/`), by shell or Edit/Write.
