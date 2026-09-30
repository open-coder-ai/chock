---
name: block-no-verify
description: "Best-effort guard against bypassing git hooks via git commit/push --no-verify, commit's short -n form, or any way of pointing core.hooksPath elsewhere: -c, --config-env, `git config core.hooksPath <path>` and the GIT_CONFIG_* environment. Read as a parsed command, so `cd repo && git commit --no-verify`, `bash -c '...'` and sudo/env/xargs wrappers are caught and a message that merely says --no-verify is not. On git push, -n means --dry-run and stays allowed. Known bypass classes include aliases, wrapper scripts, and non-standard clients. Also refuses an agent command that sets a person-only override (CHOCK_ALLOW*, CHOCK_AGENT_COMMIT, CHOCK_DIFF_LIMIT) by env prefix, env, export, declare, set/setx or $env:, and refuses hiding the agent markers (CLAUDECODE, AI_AGENT, CHOCK_AGENT_COMMIT) by unset, env -u/-i, export -n or Remove-Item Env:; it tells the agent to ask the person. Fix the underlying hook failure instead of skipping validation."
metadata:
  chock.artifact: rule
  chock.enforcement: advise
  chock.coverage_without_chock: advisory
---

# Block No-Verify

Best-effort guard against bypassing git hooks via git commit/push --no-verify, commit's short -n form, or any way of pointing core.hooksPath elsewhere: -c, --config-env, `git config core.hooksPath <path>` and the GIT_CONFIG_* environment. Read as a parsed command, so `cd repo && git commit --no-verify`, `bash -c '...'` and sudo/env/xargs wrappers are caught and a message that merely says --no-verify is not. On git push, -n means --dry-run and stays allowed. Known bypass classes include aliases, wrapper scripts, and non-standard clients. Also refuses an agent command that sets a person-only override (CHOCK_ALLOW*, CHOCK_AGENT_COMMIT, CHOCK_DIFF_LIMIT) by env prefix, env, export, declare, set/setx or $env:, and refuses hiding the agent markers (CLAUDECODE, AI_AGENT, CHOCK_AGENT_COMMIT) by unset, env -u/-i, export -n or Remove-Item Env:; it tells the agent to ask the person. Fix the underlying hook failure instead of skipping validation.

```
never(commit): --no-verify|-n; never(push): --no-verify; never(set): core.hooksPath
if(hook_fails): fix_issue; never(skip_hook)
```

This skill is advisory: the client reading it has no mechanism to enforce it, and this policy stays advisory even when compiled by `chock` -- it ships rule text, not a blocking hook. See https://github.com/open-coder-ai/chock
