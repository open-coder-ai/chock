"""What a gate's declared action is worth to coverage: a warning never refuses, so it is never credited."""

from __future__ import annotations

from typing import Any

from chock.compile.surface_kinds import Surface

WARN = "warn"

#: Surfaces a gate alone puts a policy on. The agent's own pre-tool surfaces are also a shell
#: guard's, so they are dropped only when the policy ships no guard.
_GATE_SURFACES = frozenset({Surface.GIT_HOOK, Surface.CI_GATE, Surface.STOP})
_AGENT_SURFACES = frozenset({Surface.PRE_TOOL_USE, Surface.AGENT_HOOKS})


def credited_surfaces(emitted: set[Surface], manifest: dict[str, Any], *, has_guard: bool) -> set[Surface]:
    """`emitted`, less what a warn-only gate cannot claim.

    An `ask` stays: a person decides, and on a hook that decision is a refusal until they say
    otherwise. A `warn` never refuses anywhere, so a policy whose only mechanism warns is
    graded on what it also ships (an ambient rule reads as advisory, nothing as none).
    """
    gate = (manifest.get("hook") or {}).get("gate") or {}
    if gate.get("action") != WARN:
        return emitted
    return emitted - _GATE_SURFACES - (frozenset() if has_guard else _AGENT_SURFACES)
