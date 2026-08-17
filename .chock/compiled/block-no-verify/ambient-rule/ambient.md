<!-- chock:hooks:start (compiled by chock -- edit .agents/policies/block-no-verify/) -->
```
never(commit|push): --no-verify|-n
if(hook_fails): fix_issue; never(skip_hook)
```
<!-- chock:hooks:end -->
