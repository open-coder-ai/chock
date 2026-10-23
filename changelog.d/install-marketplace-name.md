- **`chock install --marketplace-name <name>` names the build's local marketplace.** Without it nothing changes
  (`chock-local`). A team's own build, for example `--marketplace-name acme-chock`, installs as
  `chock-guardrails@acme-chock` beside a personal `chock-guardrails@chock-local`, so adding the team folder no longer
  re-points the shared `chock-local` registration and every plugin installed from it. The marketplace file, the next
  steps, `--apply`, the removal steps and the Copilot CLI "already registered" note all use the chosen name. The name
  is lowercase letters, digits and single hyphens (at most 64); anything else is refused, and so is rebuilding a
  folder under a different name than it was built with.
