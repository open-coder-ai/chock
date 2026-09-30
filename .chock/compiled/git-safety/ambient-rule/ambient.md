<!-- chock:hooks:start (compiled by chock -- edit .agents/policies/git-safety/) -->
```
see(block-destructive-commands): force_push|reset_hard|rm_-rf; see(block-no-verify): --no-verify|skip_hooks; see(protect-main-branch): direct_commit|push(main|master)
advisory: avoid(branch_-D) without_approval; prefer(feature_branch|atomic_commits); see(limit-diff-size): commit_diff > 500_lines (CHOCK_DIFF_LIMIT), human_override_only
```
<!-- chock:hooks:end -->
