- `chock doctor --live` (preview): for each target `doctor` lists, runs the pre-tool hook command
  the client's own config file holds, as written and from the repo, in the client's shell, on that
  client's own payload. It sends the first refusing eval case of the first policy the hook runs (it
  must be refused, by that policy) and `echo chock-doctor-live` (it must be allowed): two rows,
  `live: refuses the canary` and `live: allows a harmless command`, each with the fix doctor
  already prints. With no in-agent policy on the client's shell tool the canary row is skipped. It
  runs no client, sends nothing anywhere, logs nothing (the probe runs at log level off and in its
  own session, whose state file it removes), and does not prove the client calls the hook: that is
  the heartbeat row. The per-vendor payloads and wire denies the tests used are now package data
  (`chock.doctor.payloads`), one source for the engine and the tests.
