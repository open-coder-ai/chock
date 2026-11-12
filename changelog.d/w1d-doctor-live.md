- `chock doctor --live` (preview): for each sync-route target `doctor` lists, runs chock's own
  pre-tool hook commands from the client's config file, as written and from the repo, in the
  client's shell, on that client's own payload. Only an entry byte-equal to what this engine's
  installer renders for that target is run, and only when the launcher and vendored runtime are
  this engine's; any other hook command is counted in an INFO row and never run. The installed
  policies' guard code runs, as it does in `chock check` evals. It sends the first refusing eval
  case of the first policy the hook runs (it must be refused, by that policy) and
  `echo chock-doctor-live` (it must be allowed): two rows, `live: refuses the canary` and
  `live: allows a harmless command`, each with the fix doctor already prints. Plugin-route targets
  are skipped. It runs no client, sends nothing anywhere, logs nothing (the probe runs at log level
  off and in its own session, whose state file it removes), and does not prove the client calls
  the hook: that is the heartbeat row. The per-vendor payloads and wire denies the tests used are
  now package data (`chock.doctor.payloads`), one source for the engine and the tests.
