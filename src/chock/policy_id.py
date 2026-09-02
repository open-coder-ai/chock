"""The one rule for a policy id, and where it is enforced."""

from __future__ import annotations

import re

POLICY_ID_RE = re.compile(r"^[a-z][a-z0-9-]{2,63}$")


class InvalidPolicyIdError(ValueError):
    """A policy id is unsafe to use as a path or command token, or disagrees with its folder."""


def validate_policy_id(policy_id: str, folder_name: str) -> None:
    """Raise InvalidPolicyIdError unless `policy_id` is schema-valid and equals its folder name."""
    if not isinstance(policy_id, str) or not POLICY_ID_RE.fullmatch(policy_id):
        msg = (
            f"policy id {policy_id!r} is not a valid identifier (must match {POLICY_ID_RE.pattern}); "
            "refusing to use it as a filesystem path or command token"
        )
        raise InvalidPolicyIdError(msg)
    if policy_id != folder_name:
        msg = f"policy id {policy_id!r} does not match its folder name {folder_name!r}"
        raise InvalidPolicyIdError(msg)
