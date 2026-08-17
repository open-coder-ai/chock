<!-- chock:hooks:start (compiled by chock -- edit .agents/policies/protect-main-branch/) -->
```
on(commit|push): block(forbidden_ref) refs=main|master
Direct commits/pushes to a protected branch (main|master) are blocked. Create a feature branch and open a pull request.
```
<!-- chock:hooks:end -->
