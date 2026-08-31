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
    """Return a marker file describing the AGENTS.md ambient block for this policy."""
    policy_id = manifest.get("id", policy_dir.name)
    pointer = _pointer(policy_dir)
    dest = output_dir / "ambient.md"

    lines = advisory_lines(Path(policy_dir), manifest, repo_root_from_output(output_dir))
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
