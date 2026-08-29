# Onboarding interview (chock-init)

run_after: activation
ask: <=3 questions per batch; skip already answered
then: delegate to `chock init` with the collected flags

## Batch 1 — agent selection

1. which agents does the team run? map marketing names to `--agents` vocabulary
   (see `references/adapters.md`; the valid names are the keys of `CHOCK_AGENT`):
   - "Claude Code" → claude; "GitHub Copilot" → copilot; "Gemini CLI" → gemini
   - "Cursor" → cursor; "Windsurf/Codeium" → windsurf; "OpenAI Codex" → codex
   - "Devin" → devin; "Grok Build" → grok; "Kimi Code" → kimi-code
   - "VS Code custom agents" → vscode; "Aider" → aider; "Replit Agent" → replit; "Tabnine" → tabnine
   - qwen, jules, goose, amp, cody: read `AGENTS.md` natively — no wrapper, no flag name
2. no answer → default trio: claude, copilot, gemini (only claude gets a dedicated file --
   copilot and gemini read `AGENTS.md` natively; see `references/adapters.md`)
3. "all of them" / unsure and broad → `--agent-agnostic` (every supported adapter)

## Batch 2 — repo state

1. is the repo git-initialized? hooks require `.git/`; if absent, ask to run `git init` first
2. existing `AGENTS.md`? init preserves it and manages only its marker section
   (`chock:pointer` markers) — confirm nothing hand-written will be lost
3. re-run? adding/removing agents on re-run adds/removes only chock's own marker block in
   each agent's file (agentseam's shared-file model, see `references/adapters.md`) --
   adopter content elsewhere in that file, or in AGENTS.md, is never touched

## Then

1. summarize: agent list (or agnostic), repo path, files to be created
2. run `chock init` with the flags; unknown agent names abort before any write
3. report created files, preserved files, and next steps (`chock add <id>`, `chock sync --repo .`)
