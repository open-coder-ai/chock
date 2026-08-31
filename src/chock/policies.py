"""Locate installed policy folders."""

from __future__ import annotations

from pathlib import Path

from chock.manifest import CANONICAL_MANIFEST


def discover_policy_dirs(repo_root: Path) -> list[Path]:
    """Discover installed policy directories under .agents/policies."""
    policies_dir = repo_root / ".agents" / "policies"
    if not policies_dir.exists():
        return []
    dirs: list[Path] = []
    seen: set[Path] = set()
    for manifest in sorted(policies_dir.rglob(CANONICAL_MANIFEST)):
        pack = manifest.parent
        if pack.name == "evals" or pack in seen:
            continue
        seen.add(pack)
        dirs.append(pack)
    return dirs
