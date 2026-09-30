<!-- chock:hooks:start (compiled by chock -- edit .agents/policies/block-wildcard-agent-permissions/) -->
```
on(commit|tool_use): block(content_regex) scan=added_lines allowlist_pragma=pragma:\s*allowlist\s+broad-agency ...
Wildcard agent permission grant detected. Scope the grant to specific tools or commands (e.g. Bash(git status:*), a named tool list). 'pragma: allowlist broad-agency' on the same line marks a reviewed exception; in the agent (tool use, the turn's end) it counts only when that exact line is already committed in HEAD, so an agent asks a person rather than writing the pragma itself.
```
<!-- chock:hooks:end -->
