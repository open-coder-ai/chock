- `chock check --floor --base <ref> [--head <rev>] [--head-ref <branch>] [--format sarif --output <file>]`
  (preview): judges what a pull request will land. The base must be an ancestor of the head (pass GitHub's
  `refs/pull/<n>/merge` or the merge queue's head; anything else is undecided). Everything comes from the tree
  diff `base..head` (no renames, no external diff or textconv) and the commits in it; no merge-base is computed.
  Exit 0 clean, 1 refused, 2 undecided.
- Control plane: a change (add, edit, delete, mode) to any path in `src/chock/data/control_plane.json`
  (`.chock/**`, `chock.lock`, `.agents/policies/**`, every vendor hook or settings file chock and agentseam write,
  with local and override variants, `.github/workflows/**`, `.github/actions/**`, `CODEOWNERS`, `.gitattributes`;
  matched case-blind) is reported as `floor/control-plane-changed` with every path, first. These files define the
  guardrails; the floor does not judge whether a change to them is safe. A person decides. The base's
  `.chock/config.yaml` sets `floor.control_plane`: `refuse` (default, exit 1: every guardrail change, including a
  policy upgrade, a `chock sync` regeneration or a workflow edit, needs a privileged merge) or `listed` (exit 0,
  paths still listed and in the SARIF; the adopter relies on code-owner review, and content inside listed paths is
  not judged). `floor.control_plane_paths: {add, remove}` edits the list. The head's config is never read.
- Everything else is judged by the base's compiled ci gates and rollout, run by this engine; no head file executes.
  `ask` refuses; a gate that crashes, times out or cannot be read is undecided whatever the rollout. A waiver counts
  only on a line present and unchanged in both base and head. Script gates receive deleted paths under `deleted`
  and an environment of `PATH`, `HOME` (and `SYSTEMROOT`) only (script payload contract version 2,
  `spec/gate-dsl.md`).
- A per-commit pass runs the base's content gates (both surfaces) over every blob a commit in `base..head` adds or
  changes outside the control plane, read as latin-1, as utf-8 when valid, and, for a blob with a NUL byte, as
  utf-16 in both byte orders and alignments, lines split on `\n` only. A range past the commit limit or a blob over
  64 MiB is undecided, naming the commit and path. Not seen: other encodings, compressed or encoded content, commit
  messages, file names.
- It holds only as a required status check the pull request cannot redefine; that is the adopter's setting, which
  chock does not verify. It judges committed content only.
- `chock history`'s `load_rules` takes the compiled surfaces to read; its own defaults are unchanged.
