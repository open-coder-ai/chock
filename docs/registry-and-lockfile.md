# Registry & Lockfile

Two mechanisms keep a Chock install **reproducible** and **tamper-evident**: the registry
(an index of every artifact) and the lockfile (a hash-pinned record of installed packs).

## The registry

`chock registry scan` builds `.chock/registry.json` — one entry per artifact with its
id, type, version, path, trust tier, lifecycle status, dependencies, and a **`sha256` of every
deterministic script** it ships.

```bash
chock registry scan            # rebuild the index
chock registry list            # list artifacts
chock registry resolve <id>    # resolve an id to its best entry
```

### Registry freshness in CI

CI regenerates the registry and diffs it against the committed copy; a non-empty diff fails the build.
This catches the classic mistake of editing a policy without rescanning. Two things make the hashes
**stable across operating systems**:

- `.gitattributes` pins `*.sh` / `*.ps1` / `*.py` / `*.yaml` to `eol=lf`, so script bytes are identical
  on Linux and Windows.
- The scanner sorts its file iteration, so `script_hashes` key order is deterministic regardless of
  filesystem order.

> If your PR touches a policy, run `chock registry scan` and commit the result.

## The lockfile

`chock.lock` is a pinned record of every installed policy. `init` creates it and
`recompile` keeps it current, so it learns about a policy the moment you copy one in and compile.

```json
{
  "lockfile_version": "1",
  "engine": ">=0.1,<0.2",
  "packs": [
    {
      "id": "protect-main-branch",
      "version": "0.0.1",
      "managed": false,
      "sha256": "…",
      "artifacts_sha256": "…",
      "source": "local"
    }
  ]
}
```

- **`managed: false`, `source: local`** — every pack, always. The framework ships no policies, so
  there is no framework-owned tree to distinguish from yours: content is installed, and once
  installed it is yours.
- **`sha256`** — a content hash of the whole pack (`.agents/policies/<id>`) — the source you author.
- **`artifacts_sha256`** — a content hash of `.chock/compiled/<id>` — the output that
  actually enforces. Absent until the pack has been compiled; a lockfile written before this field
  existed verifies as *unpinned*, not as a mismatch.

A freshly initialised repo has `"packs": []`, because `init` installs nothing.

## Verifying a repo

```bash
chock check --only verify        # "all packs match lockfile", or fails naming the drifted pack
```

`verify` recomputes each pack's hash and compares it to the lockfile, so you always know whether an
installed policy has been altered since it was compiled.

Editing an installed policy is expected — it is yours. `verify` does not forbid it; it makes the
change **visible**. Recompile to re-pin the new hash once the edit is deliberate.

## Upgrading a policy

There is no `managed` tree to re-sync, so upgrading is explicit: copy the newer folder from the
catalog over your own and recompile. `verify` tells you beforehand whether you had local edits that
the copy would discard. (Registry-backed `add` / `upgrade`, which would make this a three-way merge
instead of a copy, are tracked in
[#15](https://github.com/open-coder-ai/chock/issues/15).)

## Why hashes, not just versions

A version says "which release"; a hash says "exactly these bytes." Because the guards are security
controls, tamper-evidence matters: `verify` turns a silent edit to an installed guard into a loud,
named failure.

## Why two hashes

Pinning only the source pack attested the wrong file. What blocks a commit is the compiled gate, not
the manifest it came from, and for a while nothing hashed it: deleting
`.chock/compiled/<id>/git-hook/gate.json`, or editing its regex so it matched nothing, left
`verify` reporting *all packs match lockfile* while the policy enforced nothing at all.

A missing control is a gap. A missing control that the tool certifies as present is a false
attestation — worse, because it is the line you would quote as evidence. `artifacts_sha256` closes
that: the lockfile now pins both what you wrote and what runs.

Two related checks cover the rest of the enforcement path. `chock sync --repo . --check`
proves the compiled tree still matches the manifests it was generated from, and `chock
validate` reports the same drift at commit time through the installed pre-commit hook. Both also
compare the vendored runtimes in `.chock/bin/` — `gate.py` executes every declarative gate,
so replacing its `run()` with `return 0` would otherwise disable every policy in the repo at once.
