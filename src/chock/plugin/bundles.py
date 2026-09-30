"""Bundles: named policy sets installed as one plugin. The data, the schema check and the grades."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import jsonschema
import yaml

from chock.validation.loading import load_schema

BUNDLES_FILE = "bundles.yaml"
_SCHEMA = "bundles.schema.json"


class BundleError(ValueError):
    """A bundles file that cannot be packaged: schema, duplicate ids, unknown or colliding members."""


def load_bundles(path: Path) -> list[dict[str, Any]]:
    """The bundles in `path`, schema-checked, in file order."""
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    errors = sorted(jsonschema.Draft7Validator(load_schema(_SCHEMA)).iter_errors(data), key=lambda e: list(e.path))
    if errors:
        found = "; ".join(f"{'/'.join(map(str, e.path)) or '<root>'}: {e.message}" for e in errors)
        msg = f"{path}: {found}"
        raise BundleError(msg)
    bundles = data["bundles"]
    ids = [b["id"] for b in bundles]
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    if dupes:
        msg = f"{path}: duplicate bundle id(s): {', '.join(dupes)}"
        raise BundleError(msg)
    nested = sorted({m for b in bundles for m in b["members"] if m in ids})
    if nested:
        msg = f"{path}: a bundle cannot contain a bundle: {', '.join(nested)}"
        raise BundleError(msg)
    return bundles


def check_members(bundles: list[dict[str, Any]], policy_ids: set[str]) -> None:
    """Every member is a known policy and no bundle shadows a policy's plugin name."""
    for bundle in bundles:
        if bundle["id"] in policy_ids:
            msg = f"bundle id {bundle['id']!r} is also a policy id; the two would package into one directory"
            raise BundleError(msg)
        unknown = [m for m in bundle["members"] if m not in policy_ids]
        if unknown:
            msg = f"bundle {bundle['id']!r} names unknown policies: {', '.join(unknown)}"
            raise BundleError(msg)


def bundle_description(purpose: str, members: list[tuple[str, str]]) -> str:
    """The bundle's claim, member by member; the posture suffix is added by the client's own manifest."""
    return f"{purpose.strip()} Members: " + "; ".join(f"{name}: {what}" for name, what in members) + "."
