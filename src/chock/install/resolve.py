"""Check every selected policy against the catalog at the pinned commit, with `chock add`'s own checks."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from chock import yamlio
from chock.compile.compiler import _load_manifest
from chock.install.selection import catalog_entries
from chock.plugin.bundle_build import Member
from chock.scaffold.add import IntegrityError, verified_pack

REGISTRY = "registry.yaml"
REFUSED = "Nothing was installed."


def _registry(catalog: Path, ref: str) -> dict[str, dict[str, Any]]:
    path = catalog / REGISTRY
    if not path.is_file():
        msg = f"the catalog at {ref} has no {REGISTRY}. {REFUSED}"
        raise IntegrityError(msg)
    data = yamlio.safe_load(path.read_text(encoding="utf-8")) or {}
    return {str(e.get("id")): e for e in data.get("policies", []) or [] if isinstance(e, dict)}


def registry_ids(catalog: Path, ref: str) -> set[str]:
    """Every policy id the catalog's registry lists at `ref`."""
    return set(_registry(catalog, ref))


def members(catalog: Path, selection: dict[str, Any]) -> list[Member]:
    """One packaging member per catalog entry; refuses on a missing id, a version or a hash mismatch."""
    ref = selection["catalog"]["ref"]
    registry = _registry(catalog, ref)
    found = []
    for pick in catalog_entries(selection):
        policy_id = pick["id"]
        entry = registry.get(policy_id)
        if entry is None:
            msg = f"{policy_id}: not in the catalog's {REGISTRY} at {ref}. {REFUSED}"
            raise IntegrityError(msg)
        if str(entry.get("version")) != pick["version"]:
            msg = (
                f"{policy_id}: the selection names version {pick['version']}, the catalog at {ref} has "
                f"{entry.get('version')}. {REFUSED}"
            )
            raise IntegrityError(msg)
        try:
            src, _area, _digest = verified_pack(catalog, policy_id, pick["sha256"])
        except FileNotFoundError as exc:
            msg = f"{exc}. {REFUSED}"
            raise IntegrityError(msg) from exc
        manifest = _load_manifest(src)
        if not manifest:
            msg = f"{policy_id}: not a policy (no manifest.yaml) in the catalog at {ref}. {REFUSED}"
            raise IntegrityError(msg)
        found.append(Member(src, manifest))
    return found
