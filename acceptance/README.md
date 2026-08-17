# Tier 1 — framework acceptance

Runs on every CI build as its own job. The rationale for this tier, and the rules that keep it
honest, are in [`conftest.py`](conftest.py) — next to the harness they constrain.

```bash
pip install build
python -m pytest acceptance/ -c acceptance/pytest.ini --rootdir=acceptance
```

## What this is

Chock as an adopter receives it: a wheel built from a clean copy, installed into an
isolated venv, driven as subprocesses in throwaway git repos. It asserts only on what an
adopter can observe -- exit codes, output, files, and whether git actually refused.

**It never imports `chock`.** `test_isolation.py` enforces that, because the rule
erodes the first time obeying it is inconvenient, and a suite that can reach into the source
tree stops testing what ships.

## Why it exists

281 internal tests were green while the wheel shipped without 42 template files, `init`
installed 10 of the 12 policies it bundles, PreToolUse enforced nothing, and a clean install
warned about every policy it had just installed. All invisible from inside.

## Scope

Tier 1 tests the **framework**, using a fixture policy the suite owns. Whether
`scan-secrets` catches AKIA keys is tier 2 and lives with that policy -- using a shipped
policy here would mean tightening its regex could fail this suite, and would only show the
framework works for policies we ship rather than for any policy an adopter writes.
