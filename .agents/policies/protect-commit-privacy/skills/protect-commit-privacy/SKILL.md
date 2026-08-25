---
name: protect-commit-privacy
description: "Keep the development conversation out of git history. Agent-authored commits narrate by default -- who asked for what, which discussion decided it, what the plan was -- and on a public repo that narration is published forever. The guard refuses git commit commands whose message (inline -m/--message or the file behind -F/--file) contains process-leak markers; the rule tells the agent to describe the change, not the conversation, and to propose sensitive messages to the human before committing. Best-effort: markers are a narrow deny-list, and a message the human explicitly approves can say anything -- edit the marker list in the guard, the content is yours."
metadata:
  chock.artifact: rule
  chock.enforcement: advise
  chock.coverage_without_chock: advisory
---

# Protect Commit Privacy

Keep the development conversation out of git history. Agent-authored commits narrate by default -- who asked for what, which discussion decided it, what the plan was -- and on a public repo that narration is published forever. The guard refuses git commit commands whose message (inline -m/--message or the file behind -F/--file) contains process-leak markers; the rule tells the agent to describe the change, not the conversation, and to propose sensitive messages to the human before committing. Best-effort: markers are a narrow deny-list, and a message the human explicitly approves can say anything -- edit the marker list in the guard, the content is yours.

```
commit_message|pr_description: describe(change); never(narrate: conversation|plan|who_asked|user_quotes|session_refs|internal_doc_paths)
if(sensitive_context): propose_message_to_human; await(approval) before(commit)  # history is published forever
```

This skill is advisory: the client reading it has no mechanism to enforce it, and this policy stays advisory even when compiled by `chock` -- it ships rule text, not a blocking hook. See https://github.com/open-coder-ai/chock
