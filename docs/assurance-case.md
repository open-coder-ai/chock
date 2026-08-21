# Assurance case

What this document is: the security argument, in one place — the top-level claim the
project makes, the threat model it defends against, and for each security requirement
the mechanism that meets it and the evidence that the mechanism works. The per-invariant
detail lives in [spec/enforcement-matrix.md](../spec/enforcement-matrix.md) and
[docs/security/README.md](security/README.md); [SECURITY.md](../SECURITY.md) documents
reporting, the catalog trust model, and hook bypassability. This page is the argument
that connects them.

## Top-level claim

**An adopter repo using Chock knows exactly which policies are enforced, by which
mechanism, on which agent — and cannot silently lose that enforcement.**

Deliberately, the claim is about *truthful, tamper-evident* enforcement, not total
prevention. Chock is a governance layer, not a sandbox: a determined human with a
terminal can bypass git hooks, and an agent outside every wired surface sees only
advisory text. The design goal is that every such gap is *stated* — in the coverage
report, in SECURITY.md, in this page — never papered over. Overclaiming is treated as
the highest-severity failure the project can ship, because one discovered overclaim
discredits every honest number.

## Trust boundaries and adversaries

Boundaries: (1) the adopter repository (trusted content, versioned); (2) the agent
session (untrusted executor — it may ignore, misread, or attempt to modify guidance);
(3) the catalog (semi-trusted remote — executable content, trust-on-first-use, hash
pinned); (4) CI (the enforcement floor — the one surface a local actor cannot bypass).

Threat classes defended against:

- **T1 — Agent misbehavior in-session**: destructive commands, hook bypass flags,
  editing its own guardrails, committing secrets.
- **T2 — Malicious or compromised catalog content**: a policy folder is executable
  (guard scripts become hooks); tampered content must be detectable before and after
  install.
- **T3 — Tampering with installed artifacts**: modified compiled gates, deleted hooks,
  drifted wiring.
- **T4 — Gate bypass by construction**: commit paths the gates never see (renames,
  merge commits, non-ASCII paths, unresolvable CI ranges, missing interpreters).
- **T5 — Overclaim (the self-threat)**: the project reporting enforcement that no
  installed mechanism provides.
- **T6 — Supply-chain compromise of Chock itself**: tampered dependencies, mutable CI
  actions, tampered releases.

## Requirements → mechanisms → evidence

| Requirement | Mechanism | Evidence |
|---|---|---|
| Untrusted input is validated by allowlist (T1, T2) | Policy ids: anchored `fullmatch` against a fixed pattern, id must equal folder name; manifests: JSON Schema; agent selections: fixed allowlist; URLs: https-only; catalog paths: confinement to the catalog root | `tests/test_manifest_id_safety.py`, property-based suite (`tests/test_properties.py`), weekly atheris fuzzing of the same parsers |
| Installed content is tamper-evident (T2, T3) | `chock.lock` pins sha256 of every pack and compiled artifact; `--verify-sha` refuses mismatched content before it touches disk; `chock check --only verify` re-derives hashes | lockfile test suite; verify exercised in CI on every PR |
| Gates fail closed, not open (T4) | CI range mode exits non-zero on an unresolvable base; hook installer bakes an absolute interpreter path (a missing `python` once meant exit 127 = allow); diff filters include renames and merge commits; `core.quotePath` handled for non-ASCII paths | `tests/test_gate_bypasses.py`, `tests/test_pretooluse*.py` — each closed bypass carries its regression test |
| Enforcement claims are computed, never asserted (T5) | `coverage_level()` credits a surface only when its install is witnessed (hook present, workflow written, settings baked); packaging formats cannot raise coverage (no plugin Surface exists); empty shims report nothing | `tests/test_coverage_honesty*.py`, `tests/test_agent_plugin.py::test_packaging_raises_no_coverage_claim` |
| Compiled output is deterministic (T3, T5) | All generated artifacts written LF-normalized via one writer; PATCH releases are byte-identical by contract | golden-file suite (`tests/test_emitter_stability.py`) run in CI; `tests/test_windows_line_endings.py` |
| An agent cannot widen its own permissions (T1) | `protect-agent-config` pre-tool-use guard blocks shell writes to agent config, hooks, and compiled trees without human approval | guard evals; exercised daily in this repo's own sessions |
| Chock's own supply chain is pinned (T6) | Every GitHub Action pinned to a commit SHA; workflow tokens least-privilege; pip installs hash-pinned (`--require-hashes`); publishing via OIDC Trusted Publishing (no stored secrets); releases carry Sigstore build-provenance attestations | Scorecard (public), CodeQL on every PR, the release workflow itself |

## Secure design principles, as applied

- **Least privilege**: workflow tokens are read-only by default, write scopes granted
  per job; the tool itself requests no credentials and holds no keys.
- **Fail-safe defaults**: gates fail closed — an unresolvable CI base ref exits
  non-zero rather than passing; the hook installer bakes an absolute interpreter path,
  because a missing interpreter meant exit 127, which a host reads as *allow*; an
  uninstalled surface claims nothing rather than assuming success.
- **Complete mediation**: the CI gate re-runs the same compiled gates server-side,
  where a local `--no-verify` cannot reach; `check --only verify` re-derives hashes
  rather than trusting a prior result.
- **Economy of mechanism**: one gate definition compiles to every surface, so there is
  a single place to reason about behavior — and a single place a bypass would show up.
- **Separation of data and instructions**: repository and web content the tool
  processes is data, never commands; this is stated in the policies themselves and in
  the guards' own headers.
- **Open design**: no security property depends on secrecy — the invariants, the
  mechanisms, and the residual risks are all public, and the coverage report is
  computed from witnessed mechanisms rather than asserted.

## Common implementation weaknesses, countered

| Weakness class | Counter | Evidence |
|---|---|---|
| Command/argument injection (CWE-77/78) | No `eval`/`exec` anywhere; subprocess calls use explicit argument lists without shell interpretation; policy ids that reach emitted scripts are allowlist-validated first | `tests/test_manifest_id_safety.py` |
| Path traversal (CWE-22) | Ids restricted to one path component and required to equal their folder; catalog paths confined to the catalog root; `--force` removal paths checked against escape | `tests/test_manifest_id_safety.py` |
| Improper input validation (CWE-20) | Anchored `fullmatch` patterns, JSON Schema validation, fixed agent allowlist, https-only scheme check | property suite + weekly atheris fuzzing |
| Insecure transport (CWE-319) | https enforced at the fetch boundary; other schemes refused, not downgraded | `tests/test_frontier_ingest.py` |
| Improper handling of exceptional conditions (CWE-703) | Fail-closed gate paths; bookkeeping failures raise rather than warn | `tests/test_gate_bypasses.py`, `tests/test_adopter_safety.py` |
| Untrusted content interpreted as instructions (prompt injection) | Content treated as data by policy; invisible/direction-override Unicode blocked at commit | `block-invisible-unicode` gate + evals |
| Hardcoded credentials (CWE-798) | No credentials in the codebase; secret scanning plus the project's own `scan-secrets` gate on every commit | GitHub secret scanning, gate evals |

Static analysis (CodeQL security queries, Ruff security rules) runs on every pull
request as a standing check against this class of defect, with findings triaged to zero.

## Residual risks, stated

- **No catalog signing.** `chock add` is trust-on-first-use with hash pinning —
  detection, not prevention, of a compromised catalog (SECURITY.md states this in
  full; signing is roadmap work, not quietly assumed).
- **Hooks are bypassable outside gated agents.** `--no-verify` works for humans; the
  CI gate is the backstop and it is opt-in. The coverage report never credits an
  agent surface that is not installed.
- **Guards are best-effort filters**, not a security boundary: quoting tricks,
  aliases, and novel encodings can evade a pattern-based guard. Their value is
  raising the cost of casual violation and producing an audit trail, and their
  guard scripts say so in their own headers.
- **Fail-open hosts.** Some agent hosts ignore unexpected hook exits; where Chock
  emits for such a host, the emitted description states the fail posture rather
  than implying parity.

Each of these is a documented limit with a stated mitigation path — the assurance the
project offers is that the map matches the territory, including the holes.
