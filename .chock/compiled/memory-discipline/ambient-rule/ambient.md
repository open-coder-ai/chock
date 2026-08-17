<!-- chock:hooks:start (compiled by chock -- edit .agents/policies/memory-discipline/) -->
```
persist: decisions|preferences|non_derivable_facts; never_persist: file_contents|git_history|task_intermediates
extract(atomic_facts); consolidate(similar > 0.85); decay(stale); verify(memory) before_recommend
```
<!-- chock:hooks:end -->
