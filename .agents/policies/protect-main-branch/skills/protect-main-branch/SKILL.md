---
name: protect-main-branch
description: "Block direct commits and pushes to main or master. Enforced at commit time by reading the current branch, and at push time by parsing the refs the agent is pushing."
metadata:
  chock.artifact: hook
  chock.enforcement: block
  chock.coverage_without_chock: advisory
---

# Protect Main Branch

Block direct commits and pushes to main or master. Enforced at commit time by reading the current branch, and at push time by parsing the refs the agent is pushing.

```
on(commit|push): block(forbidden_ref) refs=main|master
Direct commits/pushes to a protected branch (main|master) are blocked. Create a feature branch and open a pull request.
```

This skill is advisory: the client reading it has no mechanism to enforce it. The same policy compiled by `chock` becomes a git hook that exits non-zero. See https://github.com/open-coder-ai/chock
