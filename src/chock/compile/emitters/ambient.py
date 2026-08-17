"""Emit an ambient AGENTS.md hook block for a policy."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from chock.compile.emitters.advisory import (
    advisory_lines,
    repo_root_from_output,
)
from chock.compile.emitters.advisory import (
    policy_pointer as _pointer,
)
from chock.emit import write_generated


def emit(policy_dir: Path, output_dir: Path, manifest: dict[str, Any]) -> list[Path]:
    """Return a marker file describing the AGENTS.md ambient block for this policy.

    The actual AGENTS.md wiring is owned by the scaffold/validation lifecycle; this
    emitter documents the intended ambient representation.
    """
    policy_id = manifest.get("id", policy_dir.name)
    pointer = _pointer(policy_dir)
    dest = output_dir / "ambient.md"

    lines = advisory_lines(Path(policy_dir), manifest, repo_root_from_output(output_dir))
    # A policy that declares no gate, no rule text and no description has nothing to say
    # here, so say only where to look. This is the fallback the old id-keyed dict applied to
    # every policy it had not heard of; it is now reachable only by an empty manifest.
    if not lines:
        lines = [f"{manifest.get('enforcement') or 'advise'}({policy_id}): see {pointer}"]

    body = "\n".join(lines)
    write_generated(
        dest,
        f"<!-- chock:hooks:start (compiled by chock -- edit {pointer}) -->\n"
        f"```\n{body}\n```\n"
        f"<!-- chock:hooks:end -->\n",
    )
    return [dest]
