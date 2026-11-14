- `chock check --floor --base <ref> [--head <rev>] [--head-ref <branch>] [--format sarif --output <file>]`
  (preview): judges what a pull request will land. The base must be an ancestor of the head (pass GitHub's
  `refs/pull/<n>/merge` or the merge queue's head; anything else is undecided). Everything comes from the tree
  diff `base..head` (no renames, no external diff or textconv) and the commits in it; no merge-base is computed.
  Exit 0 clean, 1 refused, 2 undecided.
- Control plane: a change (add, edit, delete, mode) to any path in `src/chock/data/control_plane.json` is
  reported as `floor/control-plane-changed` with every path, first. The list: `.chock/**`, `chock.lock`, the whole
  folder of every agent chock or agentseam writes into (`.agents/**`, `.claude/**`, `.codex/**`, `.cursor/**`,
  `.gemini/**`, `.windsurf/**`, `.github/hooks/**` and the rest, plugin folders such as `.claude-plugin/**`),
  `.mcp.json`, `.vscode/settings.json`, `.vscode/mcp.json`, `.env` (at any depth), `.devcontainer/**`,
  `.devcontainer.json`, `.github/workflows/**`, `.github/actions/**`, `CODEOWNERS`; agent folders match at any
  depth (`**/.claude/**`); matched case-blind. A symlink or gitlink at a parent folder of a pattern
  (`.gemini -> cfg`) matches. Every symlink at, inside or above the control plane must resolve, link by link
  from the trees at base and head, to a control-plane path or to nothing; otherwise (and for a loop, an absolute
  or out-of-repository target, or one through a submodule) the run is undecided (exit 2), naming the link and the
  fix. A base whose `.chock` is a link or a submodule is undecided, never first adoption. A control-plane path a
  commit in the range changed is named even when the tree diff leaves it as at the base. Every git call reads
  attributes from the base (`GIT_ATTR_SOURCE`; git 2.42 or newer, else undecided), so `.gitattributes` is off
  the list. Root instruction files (`AGENTS.md`, `CLAUDE.md`) are
  not on it. These files define the guardrails; the floor does not judge whether a change to them is safe. A
  person decides. The base's `.chock/config.yaml` sets `floor.control_plane`: `refuse` (default, exit 1: every
  guardrail change, including a policy upgrade, a `chock sync` regeneration or a workflow edit, needs a
  privileged merge) or `listed` (exit 0, paths still listed and in the SARIF; the adopter relies on code-owner
  review, and content inside listed paths is not judged). `floor.control_plane_paths: {add, remove}` edits the
  list; a `remove` entry that names no default pattern is undecided (exit 2); an `add` entry `name/` means
  `name/**`, a bare folder name is undecided, and an entry matching nothing at base or head is marked so. Every run prints the mode, the
  number of patterns and the base's additions and removals. The head's config is never read.
- The list is what chock knows about, not a proof of completeness. If your workflow installs chock from a file in
  the repository (`requirements*.txt`, `pyproject.toml`, a lockfile, a local action), add that file to the list.
  Renaming or moving a test file reads as a deletion and is refused by test-integrity.
- `--repo` may name a folder below the top level; every diff is computed from the top level. A file git cannot
  read at base or head is undecided (exit 2), never handed to a gate as empty text.
- Everything else is judged by the base's compiled ci gates and rollout, run by this engine; no head file executes.
  `ask` refuses; a gate that crashes, times out or cannot be read is undecided whatever the rollout. A waiver counts
  only on a line present and unchanged in both base and head. Script gates receive deleted paths under `deleted`
  and an environment of `PATH`, `HOME` (and `SYSTEMROOT`) only (script payload contract version 2,
  `spec/gate-dsl.md`).
- A per-commit pass runs the base's content gates (both surfaces) over every blob a commit in `base..head` adds or
  changes outside the control plane (renames read as a delete and an add), read as latin-1, as utf-8 when valid, and, for a blob with a NUL byte, as
  utf-16 in both byte orders and alignments, lines split on `\n` only. A range past the commit limit or a blob over
  64 MiB is undecided, naming the commit and path. Not seen: other encodings, compressed or encoded content, commit
  messages, file names.
- `--sarif` writes a log on every run; an undecided run's says `executionSuccessful: false`. Not covered: a
  Windows short name (`CLAUDE~1/`), `*.code-workspace`, submodule content (docs/floor.md).
- It holds only as a required status check the pull request cannot redefine; that is the adopter's setting, which
  chock does not verify. It judges committed content only.
- `chock history`'s `load_rules` takes the compiled surfaces to read; its own defaults are unchanged.
