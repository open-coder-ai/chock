- **`chock install` prints "To remove it:" after the install steps.** The agent's own plugin removal, then deleting the
  build folder (`chock bundle status` lists a build for as long as its folder exists), then the shared `chock-local`
  marketplace, only when no other chock build for that agent is still installed. Codex, Antigravity and Kimi Code print
  none yet: their remove command is not confirmed. `chock bundle status` still reads the build folders only; it cannot
  tell that an agent has uninstalled a build.
