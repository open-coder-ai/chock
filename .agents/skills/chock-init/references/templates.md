# Template catalog

Templates live in `assets/templates/`. Substitute `{{repo_name}}` at generation time.

| Template path | Output path | Type | Notes |
|---|---|---|---|
| `.chock/config.yaml` | `.chock/config.yaml` | machine-readable config | |
| `AGENTS.md` | `AGENTS.md` | machine-readable rules | Single source of truth |
| `.claude/CLAUDE.md` | `.claude/CLAUDE.md` | agent wrapper | Loaded at session start |
| `.cursorrules` | `.cursorrules` | agent wrapper | Legacy root fallback |
| `.cursor/rules/chock.mdc` | `.cursor/rules/chock.mdc` | agent wrapper | Modern Cursor rules (YAML frontmatter, `alwaysApply: true`) |
| `.windsurfrules` | `.windsurfrules` | agent wrapper | Legacy root fallback |
| `.windsurf/rules/chock.md` | `.windsurf/rules/chock.md` | agent wrapper | Modern Windsurf rules (YAML frontmatter, `trigger: always_on`) |
| `.devin/README.md` | `.devin/README.md` | agent wrapper | Optional; Devin reads `AGENTS.md` natively |
| `codex.md` | `codex.md` | agent wrapper | Optional pointer; Codex reads `AGENTS.md` natively |
| `.github/copilot-instructions.md` | `.github/copilot-instructions.md` | agent wrapper | Project-wide Copilot context |
| `.gemini/GEMINI.md` | `.gemini/GEMINI.md` | agent wrapper | Hierarchical context |
| `.grok/GROK.md` | `.grok/GROK.md` | agent wrapper | Optional pointer; Grok reads `AGENTS.md` natively |
| `.kimi-code/AGENTS.md` | `.kimi-code/AGENTS.md` | agent wrapper | Optional pointer; Kimi reads `AGENTS.md` natively |
| `.github/agents/chock.agent.md` | `.github/agents/chock.agent.md` | agent wrapper | VS Code custom agent (YAML frontmatter) |
| `CONVENTIONS.md` | `CONVENTIONS.md` | agent wrapper | Aider conventions file |
| `.aider.conf.yml` | `.aider.conf.yml` | Aider config | Auto-loads `CONVENTIONS.md` |
| `replit.md` | `replit.md` | agent wrapper | Replit Agent context |
| `guidelines.md` | `guidelines.md` | agent wrapper | Tabnine Agent guidelines |
| `.chock/dependency-allowlist.txt` | `.chock/dependency-allowlist.txt` | allowlist | Written if absent; preserved on re-run |
| (code constant, not this tree) | `.gitattributes` | git config | Init writes `chock.lock` / `.chock/**` / `.agents/**` as `text eol=lf` |
| (code constants, not this tree) | `.agents/policies/{AGENTS.md,CLAUDE.md}`, `.agents/skills/{AGENTS.md,CLAUDE.md}` | guardrail pair | Edit-time provenance/editing contract written by init |
| `docs/**` | `docs/**` | human-readable documentation | |

Wrapper files delegate to `AGENTS.md`; they forbid reading `README.md`, and mark `docs/` as read-on-request only (not forbidden).

## Agent discovery behavior

| Category | Agents | Discovery | Generated files |
|---|---|---|---|
| Standard adopters | codex, cursor, windsurf, devin (also goose, amp — native `AGENTS.md` readers with no wrapper and no `--agents` name) | Read `AGENTS.md` natively | `AGENTS.md` (+ optional thin wrappers) |
| Proprietary holdouts | claude, copilot, gemini, replit | Require own file | `.claude/CLAUDE.md`, `.github/copilot-instructions.md`, `.gemini/GEMINI.md`, `replit.md` (opt-in: Replit Agent auto-creates it in its workspace) |
| Config-dependent | aider, vscode | Need config or folder | `CONVENTIONS.md` + `.aider.conf.yml`, `.github/agents/*.agent.md` |
