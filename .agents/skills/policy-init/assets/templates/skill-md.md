# Template: SKILL.md (skills)

standard: agentskills.io (frontmatter + body)
constraints:
- `name` == folder name
- `description` == `manifest.yaml` description
- keep <=150 lines
replace ALL_CAPS

The emittable Markdown baseline is [`SKILL.md.tmpl`](SKILL.md.tmpl). It uses `{id}` and `{name}` placeholders.

variants:
- hybrid/code: add `## Scripts` — one line per script
- workflow: replace `## Rules` with numbered `## Steps`, each naming delegated policy/command
- finished folder must pass `npx skills-ref validate <folder>`
