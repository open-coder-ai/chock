- `chock sync` refreshes every committed `.chock/bin/` runtime that `chock sync --check` compares,
  `gate.py` included: a repo with no gate policy no longer fails the check with "differs: bin/gate.py"
  after an engine upgrade (IR-F73).
