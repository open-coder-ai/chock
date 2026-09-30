<!-- chock:hooks:start (compiled by chock -- edit .agents/policies/pin-github-actions/) -->
```
on(commit|tool_use): block(content_regex) paths=.github/workflows/*|.github/actions/* scan=added_lines allowlist_pragma=pragma:\s*allowlist\s+unpinned-action content_pattern(regex)
Unpinned GitHub Action detected: a workflow references an action by a tag or branch (owner/repo at a movable ref) rather than a full 40-character commit SHA. Pin it to the SHA -- keep the version in a trailing comment for readability -- so a re-tagged or compromised release cannot change what runs. 'pragma: allowlist unpinned-action' on the same line marks a reviewed exception; in the agent (tool use, the turn's end) it counts only when that exact line is already committed in HEAD, so an agent asks a person rather than writing the pragma itself.
```
<!-- chock:hooks:end -->
