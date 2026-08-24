# Compatibility and stability

You can now pin what you install. `chock add` records the catalog URL, ref and resolved
commit; `chock.lock` records a `sha256` over the policy source and an `artifacts_sha256`
over the compiled output; `--verify-sha` refuses an install that does not hash to what you
expected.

That makes this page necessary rather than nice to have. Once adopters hold hashes, they are
owed a statement about what may change underneath them.

## Where the project is: 0.x

**Chock is pre-1.0, and pre-1.0 means the surfaces below can change in any release.**
The published version is on the [PyPI badge](https://pypi.org/project/chock/)
(`0.4.0` at this writing). Treat every guarantee here as a description
of intent and process, not a promise of stability — the promise starts at 1.0.

Said plainly because the alternative is worse: a compatibility page that implies stability the
project has not earned is exactly the kind of overclaim the coverage taxonomy exists to prevent.

## What counts as a breaking change

Once at 1.0, a change to any of these is breaking and requires a major version:

| Surface | What is covered |
| :--- | :--- |
| **CLI** | Command names, existing flags, and exit codes. Adding a command or an optional flag is not breaking. |
| **Manifest schema** | Removing a field, narrowing an enum, or making an optional field required. Adding an optional field is not breaking. |
| **Gate spec** | `gate.json` structure, gate `kind` names, and the meaning of their `params`. |
| **Coverage taxonomy** | The values `enforced`, `enforced-at-commit`, `advisory`, `unsupported`, `disabled`, and the rules deciding which applies. Renaming one silently rewrites everybody's compliance evidence. |
| **Lockfile** | The `lockfile_version` contract and the meaning of each field. |
| **Vendored runtimes** | The interface of `.chock/bin/gate.py` and `pretooluse.py` — the arguments they accept and the exit codes they return. Adopters wire these into hooks and settings files. |

## What is explicitly not covered

- **Anything under `src/chock/` that is not the CLI.** Module paths, function signatures
  and class names are internal. Importing Chock as a library is unsupported; the CLI is
  the API.
- **The exact bytes of compiled output.** A compiler improvement can change whitespace or
  ordering in `.chock/compiled/` without changing what is enforced. **This is the one
  most likely to surprise you** — see below.
- **Human-readable output.** Log lines, progress text and error prose may be reworded. Exit
  codes are the contract; the text around them is not. Gate *block messages* are different:
  they come from a policy manifest you own, and nothing upstream rewrites them.
- **Catalog content.** Policies are content, not API. They are versioned per policy, and once
  installed they are yours — nothing overwrites them.

## Upgrading, and why `verify` may fail when nothing is wrong

`artifacts_sha256` hashes the *compiled artifact*, deliberately: pinning only the source meant a
deleted or weakened gate still reported "all packs match lockfile". The cost of that strictness
is that a framework upgrade which changes compiled output — even cosmetically — makes `verify`
report drift on a repo nobody touched.

That is working as designed, and the remedy is to re-derive rather than to trust:

```bash
chock sync --repo .   # regenerate from your manifests
chock check           # confirm nothing about enforcement changed
chock check --only evals        # replay every gate against its own suite
git diff .chock/compiled/  # read what actually changed
chock sync --repo .        # rewrite chock.lock from what is installed (check is read-only)
```

Read the diff before rewriting the lockfile. Regenerating a hash you have not looked at converts
a tamper-detection mechanism into a rubber stamp.

`chock.lock` also carries an `engine` constraint (`>=0.1,<0.2` today). Its purpose is to
let a future version recognise a lockfile it should not silently reinterpret.

## Deprecation process

From 1.0 onward:

1. The replacement ships first, so both work at once.
2. The old surface warns on use, naming the replacement, for at least one minor release.
3. Removal happens only in a major release, listed in `CHANGELOG.md`.

Before 1.0 this is best-effort. Where a change is unavoidable, the CHANGELOG entry says what
broke and what to do about it.

## Reporting a break

If an upgrade changes behaviour in a way this page does not describe, that is a bug in the page
or in the change — open an issue either way. A compatibility policy nobody corrects is decoration.
