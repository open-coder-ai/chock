---
name: protect-agent-config
description: "Guard against an agent hand-editing its own guardrails. Agent instruction files (AGENTS.md and the per-agent wrappers), permission files (.claude/settings.json, .mcp.json) and vendored enforcement (.chock/bin/, .chock/compiled/) define what the agent may do -- so a shell command that rewrites them is the agent modifying its own authority (MITRE ATLAS AML.T0081; the AIVSS self-modification factor). The guard refuses shell write-commands targeting those paths; reads pass, and regeneration through `chock sync` passes because the tool writes them itself rather than through shell editing. Best-effort and deliberately coarse: a compound command that both reads a protected file and writes elsewhere may be refused -- rewrite it in two steps. Escape for a human-approved change: include 'chock: approved-config-change' in the command."
metadata:
  chock:
    artifact: rule
    enforcement: advise
    coverage_without_chock: advisory
---

# Protect Agent Config

Guard against an agent hand-editing its own guardrails. Agent instruction files (AGENTS.md and the per-agent wrappers), permission files (.claude/settings.json, .mcp.json) and vendored enforcement (.chock/bin/, .chock/compiled/) define what the agent may do -- so a shell command that rewrites them is the agent modifying its own authority (MITRE ATLAS AML.T0081; the AIVSS self-modification factor). The guard refuses shell write-commands targeting those paths; reads pass, and regeneration through `chock sync` passes because the tool writes them itself rather than through shell editing. Best-effort and deliberately coarse: a compound command that both reads a protected file and writes elsewhere may be refused -- rewrite it in two steps. Escape for a human-approved change: include 'chock: approved-config-change' in the command.

```
agent_config(AGENTS.md|wrappers|.claude/settings|.mcp.json|.chock/bin|.chock/compiled): never(hand_edit|delete); regenerate_via(chock sync)
if(config_change_needed): propose_to_human; await(approval)  # an agent must not widen or disarm its own guardrails
```

This skill is advisory: the client reading it has no mechanism to enforce it. The same policy compiled by `chock` becomes a git hook that exits non-zero. See https://github.com/open-coder-ai/chock
