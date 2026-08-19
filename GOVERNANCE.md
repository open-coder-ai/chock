# Governance

Chock is a solo-maintainer project. This document says plainly how it is run, who
decides what, and what happens if the maintainer disappears — because a governance
tool whose own governance is undocumented would be a poor joke.

## Decision making

The maintainer ([@open-coder-ai](https://github.com/open-coder-ai)) has final say on
scope, releases, and merges — the common single-maintainer model. In practice,
decisions follow the project's published invariants rather than taste:

- Enforcement claims must be computed from witnessed mechanisms (coverage honesty).
- PATCH releases never change compiled output (machine-enforced by the golden suite).
- Every change lands as a pull request with required CI, including the maintainer's
  own — branch protection applies to everyone.

Disagree with a decision? Open an issue or a Discussion; decisions are explained,
and reversals happen when the argument is better than the invariant it challenges.

## Roles and responsibilities

- **Maintainer**: reviews and merges PRs, triages issues, cuts releases, holds the
  security-report inbox, approves policy-catalog additions, and reviews every weekly
  threat-intel digest before it merges.
- **Contributors**: anyone via pull request. Requirements are in
  [CONTRIBUTING.md](CONTRIBUTING.md) (DCO sign-off, tests for behavior changes,
  green CI). Sustained, high-quality contributors may be offered triage or commit
  rights; that decision is the maintainer's and will be recorded here when it
  first happens.
- **Security reporters**: see [SECURITY.md](SECURITY.md) — private advisories,
  acknowledged within 7 days, credited unless they prefer otherwise.

## Access continuity

Single-maintainer projects owe their users an answer to "what if you vanish":

- The repositories live under the **open-coder-ai GitHub organization**, not a
  personal account, so ownership can be extended or transferred without rewriting
  history or URLs.
- Publishing uses **PyPI Trusted Publishing (OIDC)** scoped to this repository's
  release workflow — there are no long-lived tokens that leave with a person, and
  a successor with repository access inherits the ability to release.
- Everything needed to maintain the project is in the repository itself: the build,
  tests, release workflow, policy sources, and documentation. There is no private
  infrastructure.
- **Commitment**: if the project is visibly unmaintained (no maintainer activity for
  six months) and someone credible wants to continue it, the maintainer intends to
  add maintainers or transfer stewardship rather than let it rot. Forks are also a
  legitimate continuity path — the Apache-2.0 license permits it.

## Changing this document

Like everything else: by pull request. Material governance changes are called out in
release notes.
