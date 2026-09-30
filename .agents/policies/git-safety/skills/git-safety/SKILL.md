---
name: git-safety
description: "trigger: force push, hard reset, destructive branch delete, hook bypass, direct main commits. avoid: rewriting remote history, discarding uncommitted work, skipping pre-commit checks. Install block-destructive-commands, block-no-verify and protect-main-branch for the enforced counterparts of these controls (protect-main-branch is a commit-time gate; the other two are pre-execution guards on hook-carrying clients, advisory elsewhere); this rule is the advisory layer over them plus atomic-commit guidance no gate can decide; limit-diff-size is the commit-time gate for diff size."
metadata:
  chock.artifact: rule
  chock.enforcement: advise
  chock.coverage_without_chock: advisory
---

# Git Safety Rule

trigger: force push, hard reset, destructive branch delete, hook bypass, direct main commits. avoid: rewriting remote history, discarding uncommitted work, skipping pre-commit checks. Install block-destructive-commands, block-no-verify and protect-main-branch for the enforced counterparts of these controls (protect-main-branch is a commit-time gate; the other two are pre-execution guards on hook-carrying clients, advisory elsewhere); this rule is the advisory layer over them plus atomic-commit guidance no gate can decide; limit-diff-size is the commit-time gate for diff size.

```
see(block-destructive-commands): force_push|reset_hard|rm_-rf; see(block-no-verify): --no-verify|skip_hooks; see(protect-main-branch): direct_commit|push(main|master)
advisory: avoid(branch_-D) without_approval; prefer(feature_branch|atomic_commits); see(limit-diff-size): commit_diff > 500_lines (CHOCK_DIFF_LIMIT), human_override_only
```

This skill is advisory: the client reading it has no mechanism to enforce it, and this policy stays advisory even when compiled by `chock` -- it ships rule text, not a blocking hook. See https://github.com/open-coder-ai/chock
