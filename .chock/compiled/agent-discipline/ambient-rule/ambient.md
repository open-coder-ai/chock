<!-- chock:hooks:start (compiled by chock -- edit .agents/policies/agent-discipline/) -->
```
before(edit): read(file); before(done): verify(flow) + tests_pass + lint_clean
never(fix_test_by): delete_assertion|weaken_check|skip; on_find(dead_code|unused): delete
```
<!-- chock:hooks:end -->
