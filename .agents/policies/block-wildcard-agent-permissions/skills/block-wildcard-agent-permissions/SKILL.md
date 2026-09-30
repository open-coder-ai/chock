---
name: block-wildcard-agent-permissions
description: "The mechanizable slice of excessive agency, enforced at two points: at commit (the git hook, over staged changes) and at agent tool-use (over a tool call's arguments, as the agent writes) -- agent permission grants that allow everything. A settings file whose shell grant or allow-list is a bare wildcard hands the agent unlimited tool authority for every future session, in a file reviewers rarely read as code. The agent-world twin of block-wildcard-iam: scope grants to what the task needs (e.g. Bash(git status:*)). The allow/alwaysAllow/tools/defaultMode keys match whether or not YAML-style config quotes them, word-bounded so \"disallow\"/\"allowlist\" are not mistaken for \"allow\". Escape: 'pragma: allowlist broad-agency' on the same line."
metadata:
  chock.artifact: hook
  chock.enforcement: block
  chock.coverage_without_chock: advisory
---

# Block Wildcard Agent Permissions

The mechanizable slice of excessive agency, enforced at two points: at commit (the git hook, over staged changes) and at agent tool-use (over a tool call's arguments, as the agent writes) -- agent permission grants that allow everything. A settings file whose shell grant or allow-list is a bare wildcard hands the agent unlimited tool authority for every future session, in a file reviewers rarely read as code. The agent-world twin of block-wildcard-iam: scope grants to what the task needs (e.g. Bash(git status:*)). The allow/alwaysAllow/tools/defaultMode keys match whether or not YAML-style config quotes them, word-bounded so "disallow"/"allowlist" are not mistaken for "allow". Escape: 'pragma: allowlist broad-agency' on the same line.

```
on(commit|tool_use): block(content_regex) scan=added_lines allowlist_pragma=pragma:\s*allowlist\s+broad-agency ...
Wildcard agent permission grant detected. Scope the grant to specific tools or commands (e.g. Bash(git status:*), a named tool list). 'pragma: allowlist broad-agency' on the same line marks a reviewed exception; in the agent (tool use, the turn's end) it counts only when that exact line is already committed in HEAD, so an agent asks a person rather than writing the pragma itself.
```

This skill is advisory: the client reading it has no mechanism to enforce it. The same policy compiled by `chock` becomes a git hook that exits non-zero. See https://github.com/open-coder-ai/chock
