# The CI floor: `chock check --floor` (preview)

`chock check --floor --base <base> --head <merge result>` judges what a pull request will land, using the
**base's** gates, run by this engine. It is a preview, and it holds only under the conditions below.

## What it claims

- **Judge what will land.** The base must be an ancestor of the head; pass GitHub's `refs/pull/<n>/merge`, or the
  merge queue's head. Everything comes from the tree diff `base..head` (no renames, no external diff or textconv)
  and from the commits in it. Every git call reads attributes from the base (`GIT_ATTR_SOURCE`, git 2.42 or newer),
  so a `.gitattributes` the pull request adds changes nothing the floor sees.
- **Control plane.** A change (add, edit, delete, mode) to a path on the list in
  `src/chock/data/control_plane.json` is reported as `floor/control-plane-changed`, every path, one per line. A
  path that a commit in the range changed, even if a later commit changed it back, is named too. These files
  define the guardrails; the floor does not judge whether a change to them is safe. A person decides.
- **Links.** Every symbolic link at, inside or above a control-plane path is resolved from the trees at base and
  head, link by link. If it opens a path that is itself control plane, or nothing, the run carries on, and each
  link passed on the way is control plane too. Otherwise the run is undecided (exit 2), naming the link and its
  target. So is a loop, an absolute target, a target outside the repository, or one that passes through a
  submodule. The fix: put the target on `floor.control_plane_paths.add` in the base's config, or replace the link
  with real files. A base whose `.chock` is a link or a submodule is undecided too.
- **Everything else** is judged by the base's compiled ci gates and rollout. No file from the head executes.
  `ask` refuses. A gate that crashes, times out or cannot be read is undecided, whatever the rollout. A waiver
  counts only on a line present and unchanged in both base and head.
- **History.** The base's content gates read every blob a commit in the range adds or changes outside the control
  plane.
- **Exit codes:** 0 clean, 1 refused, 2 undecided. `--sarif <file>` writes a log on every run, with
  `executionSuccessful: false` when the run is undecided.

## Configuration (the base's `.chock/config.yaml`; the head's is never read)

```yaml
floor:
  control_plane: refuse        # default: exit 1 on any listed path. `listed`: exit 0, paths still listed
  control_plane_paths:
    add: [infra/]              # `name/` or `name/**` is the folder and all in it; a bare folder name is exit 2
    remove: ["**/.env"]        # must name a default pattern exactly, or the run is exit 2
```

Each run prints the mode, the number of patterns and the base's additions and removals. An added entry that
matches no path at base or head is marked as matching nothing.

## Conditions and limits

- **A required status check the pull request cannot redefine.** The floor holds only as one. That is the
  repository's own setting, and chock does not verify it.
- **Committed content only.**
- **Under `refuse`,** every guardrail change needs a privileged merge: a policy upgrade, a `chock sync`
  regeneration or a workflow edit.
- **Under `listed`,** you rely on code-owner review of the listed paths. The content inside them is not judged.
- **The list is what chock knows about,** not a proof of completeness. If your workflow installs chock from a file
  in the repository (`requirements*.txt`, `pyproject.toml`, a lockfile, a local action), add that file to the
  list.
- **Renames.** Renaming or moving a test file reads as a deletion, and test-integrity refuses it.

## Not covered

- **Windows short names.** The 8.3 alias of a listed folder (`CLAUDE~1/...` for `.claude/`) is not matched. This
  is untested on Windows.
- **`*.code-workspace` files.** They are not on the list: it is not verified that an editor honours hook settings
  from one.
- **Submodule content.** Only the pointer is seen. A pointer at or inside a control-plane folder is listed, but a
  submodule's own agent folders are not read.
- **What the history pass does not see:** other encodings (utf-32, compressed or encoded content), commit
  messages and file names.
- **Back-merges.** A path is named from history when a commit leaves it in a state the base does not have. A
  branch that merged an older base, from before a later change to that path, is named for it.
