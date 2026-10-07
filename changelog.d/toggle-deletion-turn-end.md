- **A deleted guardrails toggle file no longer refuses a turn end (Codex witness, 2026-10-07).** An absent
  `.chock/guardrails.json` means every member is on, so deleting it only tightens. The turn-end check now
  passes it and drops the stale record; `chock bundle status` still reports it. Deleting the repository file
  still refuses when the user file that then governs switches a member off or has no record. A file changed,
  created with no record, unreadable or a link still refuses.
- **The turn-end checks judge every workspace root.** A Stop that names several `workspace_roots` (Cursor)
  checks the payload's `cwd` and every root inside a repository, one per repository, and reports each
  root's findings under its own name. They checked only the first root.
