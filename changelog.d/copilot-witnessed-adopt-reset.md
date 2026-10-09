- **Copilot and Devin are witnessed: `chock install --selection --client copilot|devin` no longer warns "Untested".**
  Installs in GitHub Copilot CLI and Devin CLI on Windows were witnessed (org-plan
  `witness/results/witness-copilot-2026-10-08.md` and `witness/results/witness-devin-2026-10-08.md`: guard, turn-end
  gate, self-protection and per-policy on/off), so the "Untested" `client` warning now names only Cursor. Both still
  warn that a gate judges what a turn wrote only at turn end, and Devin that its hooks fail open.
- **Devin's install steps say Windows needs Developer Mode.** `devin plugins install --local` creates a symbolic link,
  so on Windows it needs Developer Mode or an elevated shell; without either it fails with "os error 1314: A required
  privilege is not held by the client".
- **`chock bundle status --adopt` refuses an invalid toggle file.** It used to record a file such as `{}` as it was,
  leaving `chock bundle on|off` refusing it with no way out but deleting it. Adopt now exits non-zero, records nothing
  and names the reset: `chock bundle status --adopt --reset` rewrites each invalid toggle file in scope as a valid
  all-on file and records it. A reset never switches anything off, leaves valid files as they are and never removes a
  folder. `chock bundle on|off` on an invalid file names the same command.
