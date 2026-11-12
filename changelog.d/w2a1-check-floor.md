- `chock check --floor --base <ref> [--head <rev>] [--head-ref <branch>]` (preview): judges a pull request's
  `base...head` with the base's compiled ci gates, run by the installed engine, never `.chock/bin/gate.py` or any
  other head file. A head gate that is new or differs also runs when it is declarative; a head script gate is
  reported "not judged at floor". A waiver counts only when the base already has the line (event `ci-floor`); `ask`
  refuses; script gates receive deleted paths under `deleted` and an environment of `PATH`, `HOME` (and `SYSTEMROOT`)
  only (script payload contract version 2, `spec/gate-dsl.md`). Built-in tamper rules from `src/chock/data/tamper.json`
  refuse by name a removed hook entry, a removed or weakened compiled gate, a pack dropped from `chock.lock`, a
  deleted `.chock/bin` file and a removed job, step or trigger of the guarded workflow; regeneration is silent. A
  per-commit pass runs the base's content gates over `merge-base..head`. Exit 0 clean, 1 refused, 2 undecided. It is
  a floor only where the repository makes it a required check, which chock does not verify.
