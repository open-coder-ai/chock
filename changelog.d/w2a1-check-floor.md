- `chock check --floor --base <ref> [--head <rev>] [--head-ref <branch>]` (preview): judges a pull request's
  `base...head` with the base's compiled ci gates, run by the installed engine, never `.chock/bin/gate.py` or any
  other head file. A head gate that is new or differs also runs when it is declarative; a head script gate is
  reported "not judged at floor". A waiver counts only on a line the pull request leaves unchanged (event
  `ci-floor`); `ask` refuses; a gate that crashes, times out or cannot be read is undecided whatever the rollout.
  Script gates receive deleted paths under `deleted` and an environment of `PATH`, `HOME` (and `SYSTEMROOT`) only
  (script payload contract version 2, `spec/gate-dsl.md`). Diffs are read with `--text`.
- Built-in tamper rules (`src/chock/data/tamper.json`) compare the merge-base with the head and refuse by name: a
  removed or retyped hook entry; a hook switch-off key turned on, or a committed higher-precedence settings file
  carrying hooks (Claude Code; other vendors are printed as not covered); a deleted compiled gate, or a changed one
  with no `chock.lock` change for its pack; a pack dropped from `chock.lock`; any `.chock/bin` file or the floor's
  own workflow that is neither the merge-base's bytes nor what this engine renders. A pack whose lock entry changed
  is listed under `floor/pack-changed` with every file of it the pull request changed, and only then is its own
  source folder exempt from its own gates.
- A per-commit pass runs the base's content gates (both surfaces) over `merge-base..head`, judging binary blobs too
  (non-utf-8 bytes read as latin-1); a range past the commit limit or a blob it cannot read is undecided, naming the
  commit and path. Exit 0 clean, 1 refused, 2 undecided. It is a floor only where the repository makes it a required
  check, which chock does not verify.
- `chock history`'s `load_rules` takes the compiled surfaces to read; its own defaults are unchanged.
