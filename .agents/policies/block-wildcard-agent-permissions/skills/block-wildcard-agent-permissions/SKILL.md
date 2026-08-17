---
name: block-wildcard-agent-permissions
description: "Pre-commit gate for the mechanizable slice of excessive agency: committed agent permission grants that allow everything. A settings file whose shell grant or allow-list is a bare wildcard hands the agent unlimited tool authority for every future session, in a file reviewers rarely read as code. The agent-world twin of block-wildcard-iam: scope grants to what the task needs (e.g. Bash(git status:*)). Escape: 'pragma: allowlist broad-agency' on the same line."
metadata:
  chock:
    artifact: hook
    enforcement: block
    coverage_without_chock: advisory
---

# Block Wildcard Agent Permissions

Pre-commit gate for the mechanizable slice of excessive agency: committed agent permission grants that allow everything. A settings file whose shell grant or allow-list is a bare wildcard hands the agent unlimited tool authority for every future session, in a file reviewers rarely read as code. The agent-world twin of block-wildcard-iam: scope grants to what the task needs (e.g. Bash(git status:*)). Escape: 'pragma: allowlist broad-agency' on the same line.

```
on(commit): block(content_regex) scan=added_lines allowlist_pragma=pragma:\s*allowlist\s+broad-agency ...
Wildcard agent permission grant detected. Scope the grant to specific tools or commands (e.g. Bash(git status:*), a named tool list), or add 'pragma: allowlist broad-agency' on the same line for a reviewed exception.
```

This skill is advisory: the client reading it has no mechanism to enforce it. The same policy compiled by `chock` becomes a git hook that exits non-zero. See https://github.com/open-coder-ai/chock
