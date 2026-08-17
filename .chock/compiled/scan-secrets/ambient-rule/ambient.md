<!-- chock:hooks:start (compiled by chock -- edit .agents/policies/scan-secrets/) -->
```
on(commit): block(content_regex) scan=added_lines forbidden_path_regex=\.(env|pem|key|p12|pfx|jks|keystore)$ ...
Potential secret detected in staged changes. Remove credentials and rotate any exposed keys. Add '# pragma: allowlist secret' on the same line only for documented test fixtures.
```
<!-- chock:hooks:end -->
