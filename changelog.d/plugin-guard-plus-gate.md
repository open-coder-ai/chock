- **A plugin package ships a policy's shell guard AND its tool_use gate when the policy has both.**
  A guard used to displace the gate in every store (`claude`, `codex`, `copilot`, `cursor`,
  `devin`), so a plugin-only install of a policy like protect-agent-config refused a shell write to
  a protected path and let an Edit or Write to the same path through, while its description and
  skill called the policy enforced. Each half now ships where the client runs it: one hooks file
  wires the guard (`--guard`) and the gate (`--gate`, plus `--stop` where the turn's end blocks),
  matching what `chock sync` installs in a repo. A gate the client cannot run is neither shipped
  nor claimed. The description states both halves' fail conditions (`Shell guard: ... Write gate:
  ...`), the skill note names both, a bundle member's line and the catalog page count each half,
  and a Stop-only gate beside a guard never reads as judging the write. Two halves that would
  write different bytes to one package path, or disagree on a hooks setting, refuse to package.
  A policy with one half packages byte for byte as before. `chock plugin build --check` reports a
  tree built before this change as stale; rebuild published plugin trees after updating chock.
