- `chock doctor --live` is out of preview. Every target now ends with an `armed` row, `yes`, `no` or `unknown`
  (`"armed"` in `--json`): `yes` needs the hooks seen refusing and a session-start heartbeat, so a fresh install
  reads `unknown` until a session has started. A target with a `prompt_submit` gate also gets two prompt probes,
  a policy's refusing eval prompt and `hello`, for the clients agentseam recorded a prompt payload for. A plugin's
  hook commands are still never run.
