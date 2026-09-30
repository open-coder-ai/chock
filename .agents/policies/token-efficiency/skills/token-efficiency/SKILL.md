---
name: token-efficiency
description: "trigger: large command output, broad searches, re-reading unchanged files, front-loading references. avoid: wasting context window on low-signal content."
metadata:
  chock.artifact: rule
  chock.enforcement: advise
  chock.coverage_without_chock: advisory
---

# Token Efficiency Rule

trigger: large command output, broad searches, re-reading unchanged files, front-loading references. avoid: wasting context window on low-signal content.

```
cap(tool_output): 4000_bytes; cap(search_results): top_3; cap(retry_loops): max_3_iterations
prefer: targeted_reads|structured_output|on_demand_refs; never: re-read(unchanged_file)|load_all_upfront
```

This skill is advisory: the client reading it has no mechanism to enforce it, and this policy stays advisory even when compiled by `chock` -- it ships rule text, not a blocking hook. See https://github.com/open-coder-ai/chock
