---
name: verify-dependency-exists
description: "Block hallucinated or unknown dependencies before they enter the repo. Watches requirements.txt, pyproject.toml, package.json, and go.mod, and blocks any newly added dependency not present in the allowlist file. Opt-in: disabled by default because it requires a curated allowlist. Enable with `chock enable verify-dependency-exists` after populating .chock/dependency-allowlist.txt. Runs at commit and at agent tool-use (a manifest edit is judged against the file on disk, and at the turn's end against HEAD)."
metadata:
  chock.artifact: hook
  chock.enforcement: block
  chock.coverage_without_chock: advisory
---

# Verify Dependency Exists

Block hallucinated or unknown dependencies before they enter the repo. Watches requirements.txt, pyproject.toml, package.json, and go.mod, and blocks any newly added dependency not present in the allowlist file. Opt-in: disabled by default because it requires a curated allowlist. Enable with `chock enable verify-dependency-exists` after populating .chock/dependency-allowlist.txt. Runs at commit and at agent tool-use (a manifest edit is judged against the file on disk, and at the turn's end against HEAD).

```
on(commit|tool_use): block(dependency_allowlist) manifests=requirements.txt|pyproject.toml|package.json|... allowlist_file=.chock/dependency-allowlist.txt
Unknown dependency blocked. Verify the package exists in the official registry, then ask a person to add it to .chock/dependency-allowlist.txt -- an agent may not edit that file (protect-agent-config).
```

This skill is advisory: the client reading it has no mechanism to enforce it. The same policy compiled by `chock` becomes a git hook that exits non-zero. See https://github.com/open-coder-ai/chock
