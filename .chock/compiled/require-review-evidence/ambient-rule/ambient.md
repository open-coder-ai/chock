<!-- chock:hooks:start (compiled by chock -- edit .agents/policies/require-review-evidence/) -->
```
before(merge): pass(chock review require --base <ref>)  # required GitHub status check, see action.yml
if(fails): read the printed judgement and run the `chock review emit` command it names
```
<!-- chock:hooks:end -->
