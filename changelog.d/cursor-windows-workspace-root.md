- **Fix: Cursor's write gate on Windows judges the write inside its workspace.** Cursor sends no `cwd` and
  spells its root `/C:/...`; the gate now takes the repository root from `workspace_roots` (the one holding
  the written path), so a Write under `.github/workflows/` is judged instead of passing as outside the repository.
  The guardrails wrapper now refuses (exit 2, with the reason) when it fails before the adapter answers.
