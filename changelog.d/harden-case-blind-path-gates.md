- **Hardening: a protected path is protected in any letter case on macOS and Windows.** The write gate, the MCP
  gateway's path check and the outside-repository globs now match forbidden-path patterns and scope globs
  without regard to case on those platforms, so a protected file that does not exist yet is covered as well.
