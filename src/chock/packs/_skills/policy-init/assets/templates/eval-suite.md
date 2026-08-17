# Template: evals/suite.yaml

minimums:
- skills: >=1 trigger + >=1 negative_trigger + >=1 behavior
- hooks: >=1 enforcement fires + >=1 compliant actions pass silently

The emittable YAML baseline is [`eval-suite.yaml.tmpl`](eval-suite.yaml.tmpl). It uses the `{id}` placeholder.

v0 execution: run each case in fresh session; check `expect` manually; append to `optimization-log.yaml`.
