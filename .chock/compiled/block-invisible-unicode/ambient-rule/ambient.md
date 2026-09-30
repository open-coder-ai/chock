<!-- chock:hooks:start (compiled by chock -- edit .agents/policies/block-invisible-unicode/) -->
```
on(commit|tool_use): block(content_regex) scan=added_lines allowlist_pragma=pragma:\s*allowlist\s+invisible-unicode ...
Invisible or direction-override Unicode detected in this change. These characters change how code reads to a human or hide instructions an agent will still obey. Remove them. 'pragma: allowlist invisible-unicode' on the same line marks a documented exception; in the agent (tool use, the turn's end) it counts only when that exact line is already committed in HEAD, so an agent asks a person rather than writing the pragma itself.
```
<!-- chock:hooks:end -->
