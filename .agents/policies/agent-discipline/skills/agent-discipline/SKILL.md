---
name: agent-discipline
description: "trigger: edits without reading, unverified completion claims, weakened tests, dead code. avoid: skipping verification, deleting assertions, leaving unused code."
metadata:
  chock.artifact: rule
  chock.enforcement: advise
  chock.coverage_without_chock: advisory
---

# Agent Discipline Rule

trigger: edits without reading, unverified completion claims, weakened tests, dead code. avoid: skipping verification, deleting assertions, leaving unused code.

```
before(edit): read(file); before(done): verify(flow) + tests_pass + lint_clean; on_find(dead_code|unused): delete
never(fix_test_by): delete_assertion|weaken_check|skip; see(protect-test-integrity): deleted_test|assertion_loss|vacuous_assert; see(block-test-skips): added_skip|only
```

This skill is advisory: the client reading it has no mechanism to enforce it, and this policy stays advisory even when compiled by `chock` -- it ships rule text, not a blocking hook. See https://github.com/open-coder-ai/chock
