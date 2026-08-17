<!-- chock:hooks:start (compiled by chock -- edit .agents/policies/code-safety/) -->
```
never(commit): secrets|keys|tokens|passwords|.env; never(add): eval|exec|unsanitized_sql
before(dependency): verify(exists_in_registry); on_find(secret|hallucinated_pkg): block + remove
```
<!-- chock:hooks:end -->
