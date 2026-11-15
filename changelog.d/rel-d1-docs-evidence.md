- README: the quick start's `chock add` line no longer carries `--ref` and `--verify-sha`; the text under
  it says what the command pins by default (the catalog tag `v<chock version>`) and that `--ref` and
  `--verify-sha` still pin by hand. `docs/quickstart.sh` and the panel sources in
  `docs/assets/readme/render.mjs` follow.
- README: a short section after the quick start names `chock doctor`, `chock doctor --live` and the
  `rollout:` line in `.chock/config.yaml`.
- Witness ledger: one row, Claude Code v2.1.317 on Windows, 2026-11-11: `PreToolUse` refused
  `git commit --no-verify` on the PowerShell tool and no commit was made (chock `295b38c`). The README
  sentence on where repo hooks were tested now names it.
- Witness ledger: a second row, Cursor 3.30.14 on Windows, 2026-11-14: the repo's `beforeShellExecution` hook refused
  `git commit --no-verify` and no commit was made (chock `cc127e4`). Surface `agent-hooks`, the name the ledger's
  readers (`sync_notes`, `derive.py`) key on for repo hooks.
- README: the new section is kept to a short paragraph; the FAQ keeps its six entries. The "estimate what a late
  finding costs" paragraph and a sentence repeating the comparison link were removed to stay within the README
  budgets (1,600 words, 300 lines).
- Witness ledger: a third row, Codex CLI 0.169.0 on Windows, 2026-11-14: the repo's `PreToolUse` hook refused
  `git commit --no-verify` and no commit was made, after the project's hooks were trusted (chock `cc127e4`).
  `derive.py` now groups the ledger's clients by the platform each records, without versions, and carries the trust
  condition.
