<!-- chock:hooks:start (compiled by chock -- edit .agents/policies/memory-discipline/) -->
```
persist: decisions|preferences|non_derivable_facts; never_persist: file_contents|git_history|task_intermediates; see(guard-memory-writes): pasted_git_history|code_block>20_lines|duplicate_line|secret, enforced at commit and agent write
extract(atomic_facts); consolidate(near_duplicate_facts); decay(stale); verify(memory) before_recommend
```
<!-- chock:hooks:end -->
