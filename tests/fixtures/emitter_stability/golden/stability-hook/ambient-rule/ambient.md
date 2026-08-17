<!-- chock:hooks:start (compiled by chock -- edit .agents/policies/stability-hook/) -->
```
on(commit|push): block(forbidden_ref) refs=main
Direct commits/pushes to a protected branch (main) are blocked. Create a feature branch and open a pull request.
```
<!-- chock:hooks:end -->
