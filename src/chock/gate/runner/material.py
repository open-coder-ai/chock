"""Gate runner: a compiled gate's own paths, params, and the context its event puts under judgement."""

from __future__ import annotations

import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

from .constants import (
    _MIN_COMPILED_PATH_DEPTH,
    AGENT_EVENTS,
    COMPILED_PREFIX,
    POLICIES_PREFIX,
    SCRIPT_BASE_GATE,
    STOP_EVENT,
    WRITE_PATH_KINDS,
)
from .context import GateContext, WriteContext


# >>> gate.py 12
def own_paths(gate_path: Path) -> tuple[str, ...]:
    """Prefixes a gate never judges: its own policy's shipped and compiled files."""
    parents = gate_path.resolve().parents
    if len(parents) < _MIN_COMPILED_PATH_DEPTH or parents[2].name != "compiled":
        return ()
    policy = parents[1].name
    return (f"{COMPILED_PREFIX}{policy}/", f"{POLICIES_PREFIX}{policy}/")


def _params(gate_path: Path, spec: dict) -> dict:
    """The gate's params, with a packaged script gate's program located beside the gate file."""
    params = dict(spec.get("params", {}))
    if spec.get("script_base") == SCRIPT_BASE_GATE:
        params["script"] = str(gate_path.resolve().parent / str(params.get("script", "")))
    return params


def _context(
    event: str,
    spec: dict,
    repo_root: Path,
    push_stdin: str | None,
    base: str | None,
    head_ref: str | None,
    writes: Mapping[str, str] | None,
    added: Mapping[str, str] | None = None,
    own: Sequence[str] = (),
    session: Mapping[str, object] | None = None,
) -> GateContext | None:
    """The material this event puts under judgement, or None when the kind cannot read it."""
    if event not in AGENT_EVENTS:
        return GateContext(
            repo_root=repo_root, push_stdin=push_stdin, base=base, head_ref=head_ref, scope=spec.get("paths"), own=own
        )
    if spec.get("kind") not in WRITE_PATH_KINDS:
        print(
            f"gate: kind {spec.get('kind')!r} has nothing to read at {event} -- it asks about the "
            "repository, not about a file being written. Refusing rather than reporting an allow "
            "it never established.",
            file=sys.stderr,
        )
        return None
    return WriteContext(
        repo_root=repo_root,
        writes=writes or {},
        scope=spec.get("paths"),
        added=added,
        own=own,
        stop=event == STOP_EVENT,
        session=session,
    )
