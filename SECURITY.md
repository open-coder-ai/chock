# Security Policy

## Supported versions

| Version | Supported |
|---|---|
| 0.1.x (latest) | yes |
| older | no |

## Reporting a vulnerability

Chock is a policy-engineering framework whose artifacts run inside AI coding
agents and git hooks; vulnerabilities here can propagate into every consumer repo.

- **Preferred:** open a private security advisory:
  <https://github.com/open-coder-ai/chock/security/advisories/new>
- Do **not** open a public issue for exploitable findings.
- Include: affected artifact or tool path, reproduction steps, and impact
  (e.g. ambient-context injection, sandbox escape, script-integrity bypass).

Expect an acknowledgment within 7 days and an initial assessment within 14 days.
Confirmed vulnerabilities are fixed in a patch release, credited to the reporter
unless they prefer otherwise, with a `SEC-*` entry in the enforcement matrix when
a new invariant is required.

## Verifying a release

Releases are published to PyPI by the tag-triggered release workflow via Trusted
Publishing (OIDC — no long-lived tokens), and every release's artifacts carry a
Sigstore build-provenance attestation generated in the same run. To verify that a
distribution you downloaded was built by this repository's release workflow:

```bash
gh attestation verify chock-0.1.1-py3-none-any.whl \
  --repo open-coder-ai/chock \
  --signer-workflow open-coder-ai/chock/.github/workflows/release.yml \
  --source-ref refs/tags/v0.1.1
```

Substitute the version you downloaded in both places. `--repo` alone would accept an
attestation minted by *any* workflow in this repository; `--signer-workflow` restricts
it to the release workflow, and `--source-ref` requires it was built from that
version's tag. The attestation binds the artifact's digest to the exact source commit
and workflow that produced it. The full security argument, including what this does and does not
protect against, is in [docs/assurance-case.md](docs/assurance-case.md).

## Threat model

The framework's security invariants (SEC-1..7, DET-1..4, EXE-1..7, EFF-1) and the
checks that enforce them are documented in `spec/enforcement-matrix.md` and
`docs/security/README.md`. Those cover *authoring-time* properties. The two runtime
limits below are properties of the design rather than bugs, and are stated here
because a governance tool that leaves them implicit is claiming more than it does.

### Catalog trust model: `chock add` is trust-on-first-use

`chock add <id>` runs `git clone --depth 1` against a catalog and copies a
folder into your repo. **A catalog policy is not inert data.** Its
`implementations/*.sh` becomes a git hook that runs on every commit, and a guard
consulted before your agent executes a command. Installing one is running code from
a remote repository.

What the tooling gives you:

- Without `--ref`, `add` resolves the catalog's **default branch** — whatever it
  points at right now. The resolved commit is printed and written to
  `chock.lock` as `source_commit`, so an install is auditable afterwards.
- `--ref <tag>` pins the fetch.
- `--verify-sha <sha256>` refuses content whose hash is not the expected one, and
  the check happens **before anything is written**, so an unexpected guard script
  never reaches your disk.
- `chock check --only verify` re-checks installed packs *and* their compiled artifacts
  against the lockfile.

What it does **not** give you is signature verification. There is no signing key and
no trust root. A compromised catalog repository, or a compromised account with push
access to one, can serve content that `add` will install — pinning and hashing make
that reproducible and detectable, not impossible. Treat a third-party catalog the way
you would treat any dependency shipping executable content: review the diff, pin the
ref, and commit the hash in your lockfile.

Signing is tracked as future work rather than quietly assumed.

### Git hooks are bypassable, and the CI backstop is opt-in

`git commit --no-verify` skips every git hook, and therefore every Chock
gate. On Claude Code the `block-no-verify` policy refuses the flag before the
command runs; on other agents, and for a human at a terminal, nothing stops it. Git
hooks also live in `.git/hooks`, which is not cloned — a fresh clone enforces
nothing until someone runs `chock sync`.

The surface that closes both holes is `ci-gate`: it re-runs the same compiled gates
over a pull request's commit range, on a server, where neither `--no-verify` nor an
uninstalled hook reaches. **It is not automatic.** `compile` writes the gate;
`chock sync --ci` writes the workflow that runs it, and until that has run
the surface enforces nothing — the coverage report will not credit it either. Run:

```bash
chock sync --ci --repo .
```

Whether or not you use it, `chock check` and
`chock sync --repo . --check` belong in your pipeline: they detect a
disabled, deleted, or tampered gate, which a gate-running step alone cannot.
