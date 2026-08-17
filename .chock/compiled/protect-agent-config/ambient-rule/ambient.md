<!-- chock:hooks:start (compiled by chock -- edit .agents/policies/protect-agent-config/) -->
```
agent_config(AGENTS.md|wrappers|.claude/settings|.mcp.json|.chock/bin|.chock/compiled): never(hand_edit|delete); regenerate_via(chock sync)
if(config_change_needed): propose_to_human; await(approval)  # an agent must not widen or disarm its own guardrails
```
<!-- chock:hooks:end -->
