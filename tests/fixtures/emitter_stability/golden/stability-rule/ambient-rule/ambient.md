<!-- chock:hooks:start (compiled by chock -- edit .agents/policies/stability-rule/) -->
```
never(commit|push): --no-verify|-n
if(hook_fails): fix_issue; never(skip_hook)
```
<!-- chock:hooks:end -->
