<!-- chock:hooks:start (compiled by chock -- edit .agents/policies/block-destructive-commands/) -->
```
block(destructive_command): rm_-rf(/|~|.), git_push_--force, git_reset_--hard, git_checkout_., git_clean_-f, kubectl_delete, terraform_destroy
require_approval: reset_hard|rm_-rf|branch_-D; prefer: stash|soft_reset|force-with-lease|dry-run
```
<!-- chock:hooks:end -->
