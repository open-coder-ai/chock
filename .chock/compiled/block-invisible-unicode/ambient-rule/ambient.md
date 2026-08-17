<!-- chock:hooks:start (compiled by chock -- edit .agents/policies/block-invisible-unicode/) -->
```
on(commit): block(content_regex) scan=added_lines allowlist_pragma=pragma:\s*allowlist\s+invisible-unicode ...
Invisible or direction-override Unicode detected in staged changes. These characters change how code reads to a human or hide instructions an agent will still obey. Remove them, or add 'pragma: allowlist invisible-unicode' on the same line for a documented exception (e.g. a test fixture).
```
<!-- chock:hooks:end -->
