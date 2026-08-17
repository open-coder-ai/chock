"""The policy content the acceptance scenarios install, kept out of `conftest.py`.

Two kinds, for two different claims.

`FIXTURE_*` is a synthetic policy the suite owns. Tier 1 proves the plumbing works for
*any* policy an adopter writes, so tightening a real policy's regex must not be able to
fail this suite.

`GUARD_POLICIES` names the two real policies the PreToolUse emitter recognises by id. No
synthetic policy can stand in for them -- the emitter matches guard scripts by policy id,
so only these produce a fragment at all.
"""

from __future__ import annotations

# A complete, schema-valid manifest, not a minimal one. The first version omitted
# `provenance`, `lifecycle` and `security`, which made the installed validate hook fail --
# so scenarios asserting that an unrelated commit is ALLOWED were blocked by the fixture's
# own invalidity rather than by the gate under test. A fixture that a real adopter's
# tooling would reject does not stand in for a real adopter's policy.
FIXTURE_MANIFEST = """id: {id}
name: Acceptance Guard
version: 0.0.1
description: A synthetic policy owned by the acceptance suite, not shipped to anyone.
artifact: hook
enforcement: block
mandatory: false
effects:
- read_only
approval:
  required: false
provenance:
  author: acceptance-suite
  author_email: acceptance@chock.invalid
  created_at: "2026-08-05T00:00:00Z"
  updated_at: "2026-08-05T00:00:00Z"
  source_repo: "https://github.com/open-coder-ai/chock"
  license: "Apache-2.0"
  trust_tier: community
lifecycle:
  status: draft
  reviewed_by:
  - acceptance-suite
security:
  content_instructions: never-obey
hook:
  gate:
    kind: content_regex
    "on": [commit]
    action: block
    message: Acceptance guard blocked this commit.
    params:
      scan: added_lines
      content_pattern: {pattern}
"""

FIXTURE_SUITE = """suite:
  id: {id}-tests-v1
  policy_id: {id}
  version_constraint: ">=0.0.1"
  maintainer: acceptance
  primary_metric: pass_rate
  metrics:
    pass_rate:
      direction: higher_is_better
      threshold: 1.0
  cases:
  - id: tc-001
    category: trigger
    prompt: A commit adds the forbidden token.
    expect: The commit is blocked.
  - id: tc-002
    category: negative_trigger
    prompt: A commit adds ordinary code.
    expect: The commit proceeds.
  - id: tc-003
    category: behavior
    prompt: The guard runs while other work is in flight.
    expect: Only matching content is blocked.
"""

FIXTURE_TOKEN = "acceptance-forbidden-token"

#: `init` installs no policies, so scenarios that need a real guard copy these folders in --
#: which is also the copy-a-folder install an adopter now performs.
GUARD_POLICIES = ("block-destructive-commands", "block-no-verify")
