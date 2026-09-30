---
name: memory-discipline
description: "trigger: repeated mistakes, rediscovered patterns, preferences, non-derivable facts. avoid: persisting file contents, git history, or task intermediates as memory."
metadata:
  chock.artifact: rule
  chock.enforcement: advise
  chock.coverage_without_chock: advisory
---

# Memory Discipline Rule

trigger: repeated mistakes, rediscovered patterns, preferences, non-derivable facts. avoid: persisting file contents, git history, or task intermediates as memory.

```
persist: decisions|preferences|non_derivable_facts; never_persist: file_contents|git_history|task_intermediates; see(guard-memory-writes): pasted_git_history|code_block>20_lines|duplicate_line|secret, enforced at commit and agent write
extract(atomic_facts); consolidate(near_duplicate_facts); decay(stale); verify(memory) before_recommend
```

This skill is advisory: the client reading it has no mechanism to enforce it, and this policy stays advisory even when compiled by `chock` -- it ships rule text, not a blocking hook. See https://github.com/open-coder-ai/chock
