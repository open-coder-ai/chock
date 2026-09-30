---
name: code-safety
description: "trigger: secrets, eval/exec, unsanitized SQL, hallucinated dependencies. avoid: committing credentials, adding unverified packages, executing dynamic code. Install scan-secrets for the enforced counterpart of the secret slice (a commit-time gate), and verify-dependency-exists for the dependency slice (opt-in: disabled by default, needs a curated allowlist); the eval/exec and unsanitized-SQL guidance stays advisory (a gate can decide only the non-literal slice: agentic-code-security's code pack)."
metadata:
  chock.artifact: rule
  chock.enforcement: advise
  chock.coverage_without_chock: advisory
---

# Code Safety Rule

trigger: secrets, eval/exec, unsanitized SQL, hallucinated dependencies. avoid: committing credentials, adding unverified packages, executing dynamic code. Install scan-secrets for the enforced counterpart of the secret slice (a commit-time gate), and verify-dependency-exists for the dependency slice (opt-in: disabled by default, needs a curated allowlist); the eval/exec and unsanitized-SQL guidance stays advisory (a gate can decide only the non-literal slice: agentic-code-security's code pack).

```
see(scan-secrets): commit(secrets|keys|tokens|passwords|.env); see(verify-dependency-exists, opt_in): add(unlisted_dependency)
see(agentic-code-security pack code): refuses eval|exec of non-literal text and SQL built from strings in Python|JS; advisory: avoid(eval|exec|unsanitized_sql); on_find(secret|hallucinated_pkg): propose_removal_to_human
```

This skill is advisory: the client reading it has no mechanism to enforce it, and this policy stays advisory even when compiled by `chock` -- it ships rule text, not a blocking hook. See https://github.com/open-coder-ai/chock
