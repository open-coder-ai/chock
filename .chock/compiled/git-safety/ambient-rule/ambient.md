<!-- chock:hooks:start (compiled by chock -- edit .agents/policies/git-safety/) -->
```
never(without_approval): force_push|reset_hard|branch_-D|rm_-rf; never: --no-verify|skip_hooks
before(commit): feature_branch(not main|master); prefer: atomic_commits; ask_if(diff > 500_lines)
```
<!-- chock:hooks:end -->
