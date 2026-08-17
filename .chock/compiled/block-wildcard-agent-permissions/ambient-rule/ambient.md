<!-- chock:hooks:start (compiled by chock -- edit .agents/policies/block-wildcard-agent-permissions/) -->
```
on(commit): block(content_regex) scan=added_lines allowlist_pragma=pragma:\s*allowlist\s+broad-agency ...
Wildcard agent permission grant detected. Scope the grant to specific tools or commands (e.g. Bash(git status:*), a named tool list), or add 'pragma: allowlist broad-agency' on the same line for a reviewed exception.
```
<!-- chock:hooks:end -->
