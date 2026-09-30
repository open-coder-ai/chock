---
name: scan-secrets
description: "Blocks known credential patterns -- vendor key prefixes, private-key blocks, and key/token/password assignments -- at two enforcement points: at commit (the git hook, over staged changes) and at agent tool-use (the mcp-gateway / agent write guard, over a tool call's arguments), so a secret is caught as the agent writes it, before it ever reaches a commit. Matched by pattern, not by entropy analysis. Best-effort guard; not a replacement for a dedicated secret scanner."
metadata:
  chock.artifact: hook
  chock.enforcement: block
  chock.coverage_without_chock: advisory
---

# Scan Secrets

Blocks known credential patterns -- vendor key prefixes, private-key blocks, and key/token/password assignments -- at two enforcement points: at commit (the git hook, over staged changes) and at agent tool-use (the mcp-gateway / agent write guard, over a tool call's arguments), so a secret is caught as the agent writes it, before it ever reaches a commit. Matched by pattern, not by entropy analysis. Best-effort guard; not a replacement for a dedicated secret scanner.

```
on(commit|tool_use): block(content_regex) scan=added_lines forbidden_path_regex=(\.env(\.(?!(sample|example|template|dist|def... ...
Potential secret detected in this change. Remove credentials and rotate any exposed keys. '# pragma: allowlist secret' on the same line marks a documented test fixture; in the agent (tool use, the turn's end) it counts only when that exact line is already committed in HEAD, so an agent asks a person rather than writing the pragma itself.
```

This skill is advisory: the client reading it has no mechanism to enforce it. The same policy compiled by `chock` becomes a git hook that exits non-zero. See https://github.com/open-coder-ai/chock
