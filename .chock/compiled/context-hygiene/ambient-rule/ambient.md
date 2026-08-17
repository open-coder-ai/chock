<!-- chock:hooks:start (compiled by chock -- edit .agents/policies/context-hygiene/) -->
```
replace(resolved_content): path_ref_only; delegate(noisy_exploration): subagent; prune(stale > 3_turns)
on_context_growth: summarize(old_observations); keep(decisions+outcomes); discard(superseded_content)
```
<!-- chock:hooks:end -->
