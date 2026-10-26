- **Hardening: `chock sync` refuses an agent config that is a symlink.** Writing hooks into
  `.claude/settings.json` and the other merged vendor configs now goes through the same no-follow writer as
  the MCP registration: a link at the file or any directory above it stops the sync, and nothing is written.
  The merged config file is now written with owner-only permissions.
