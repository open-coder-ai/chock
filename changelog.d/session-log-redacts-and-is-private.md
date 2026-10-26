- **The per-session tool-call log redacts what it stores:** a command's first line and a path pass through the same
  scan-secrets redaction as the decision log, and URL userinfo inside a command is removed. `.chock/state` is created
  owner-only (the log files already were). Changes the vendored runtime: a person runs `chock sync` to render it.
