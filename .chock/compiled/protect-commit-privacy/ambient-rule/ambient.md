<!-- chock:hooks:start (compiled by chock -- edit .agents/policies/protect-commit-privacy/) -->
```
commit_message|pr_description: describe(change); never(narrate: conversation|plan|who_asked|user_quotes|session_refs|internal_doc_paths)
if(sensitive_context): propose_message_to_human; await(approval) before(commit)  # history is published forever
```
<!-- chock:hooks:end -->
