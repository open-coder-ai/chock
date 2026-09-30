<!-- chock:hooks:start (compiled by chock -- edit .agents/policies/agent-discipline/) -->
```
before(edit): read(file); before(done): verify(flow) + tests_pass + lint_clean; on_find(dead_code|unused): delete
never(fix_test_by): delete_assertion|weaken_check|skip; see(protect-test-integrity): deleted_test|assertion_loss|vacuous_assert; see(block-test-skips): added_skip|only
```
<!-- chock:hooks:end -->
