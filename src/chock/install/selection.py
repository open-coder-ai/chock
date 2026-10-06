"""Read a selection (file, `#s=` URL or bare base64url code), check it against its schema, and map it to schema 2."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
from pathlib import Path
from typing import Any

import jsonschema
import yaml

from chock import yamlio
from chock.validation.loading import load_schema

SCHEMA = "selection.schema.json"
FRAGMENT = "#s="
SCHEMA1, SCHEMA2 = 1, 2
VERSIONS = (SCHEMA1, SCHEMA2)
CATALOG, LOCAL = "catalog", "local"
#: The plugin name a selection gets when it names none; schema 1 always had this one.
DEFAULT_BUNDLE = "chock-guardrails"
#: The one client schema 1 could name.
SCHEMA1_CLIENT = "claude-code"
#: Schema 1 had no bundle version: its plugins were always listed as 1.0.0+<digest12>.
SCHEMA1_BUNDLE_VERSION = "1.0.0"


class SelectionError(ValueError):
    """A selection that cannot be read or does not match its schema."""


def _decode(code: str) -> Any:
    try:
        raw = base64.urlsafe_b64decode(code + "=" * (-len(code) % 4))
        return json.loads(raw.decode("utf-8"))
    except (binascii.Error, ValueError) as exc:
        msg = f"the selection code is not base64url-encoded JSON ({exc})"
        raise SelectionError(msg) from exc


def _is_file(path: Path) -> bool:
    """`Path.is_file`, false for a string too long to be a path (a bare code usually is)."""
    try:
        return path.is_file()
    except OSError:
        return False


def _raw(arg: str) -> Any:
    """The selection object `arg` names: a URL fragment, a file, or a bare code, in that order."""
    if FRAGMENT in arg:
        return _decode(arg.split(FRAGMENT, 1)[1])
    path = Path(arg).expanduser()
    if _is_file(path):
        try:
            return yamlio.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
            msg = f"{path}: cannot read the selection ({exc})"
            raise SelectionError(msg) from exc
    return _decode(arg.strip())


def _validator(data: Any) -> jsonschema.Draft7Validator:
    """The validator for `data`'s own schema version, so an error names that version's fields."""
    schema = load_schema(SCHEMA)
    version = data.get("schema") if isinstance(data, dict) else None
    if version in VERSIONS:
        schema = {"definitions": schema["definitions"], "$ref": f"#/definitions/v{version}"}
    return jsonschema.Draft7Validator(schema)


def check(data: Any) -> dict[str, Any]:
    """`data` if it is a schema-valid selection with unique policy ids, else SelectionError."""
    errors = sorted(_validator(data).iter_errors(data), key=lambda e: list(e.path))
    if errors:
        found = "; ".join(f"{'/'.join(map(str, e.path)) or '<root>'}: {e.message}" for e in errors)
        msg = f"invalid selection: {found}"
        raise SelectionError(msg)
    ids = [p["id"] for p in data["policies"]]
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    if dupes:
        msg = f"invalid selection: policy listed more than once: {', '.join(dupes)}"
        raise SelectionError(msg)
    return data


def upgrade(data: dict[str, Any]) -> dict[str, Any]:
    """A checked selection as schema 2: schema 1 gains the default bundle and `from: catalog` on each entry."""
    if data["schema"] == SCHEMA2:
        bundle = {"name": DEFAULT_BUNDLE, **data["bundle"]}
        return {**data, "bundle": bundle}
    upgraded = {
        "schema": SCHEMA2,
        "client": data["client"],
        "bundle": {"name": DEFAULT_BUNDLE, "version": SCHEMA1_BUNDLE_VERSION},
        "catalog": data["catalog"],
        "policies": [{"from": CATALOG, **p} for p in data["policies"]],
    }
    return {**upgraded, "preset": data["preset"]} if "preset" in data else upgraded


def load(arg: str) -> dict[str, Any]:
    """The checked selection named by `arg`, as schema 2."""
    return upgrade(check(_raw(arg)))


def catalog_entries(selection: dict[str, Any]) -> list[dict[str, Any]]:
    """The schema-2 entries pinned to the selection's catalog."""
    return [p for p in selection["policies"] if p["from"] == CATALOG]


def digest(selection: dict[str, Any]) -> str:
    """A stable hash of what a selection installs: the catalog commit and each policy's pinned hash.

    A schema-1 selection and its schema-2 form hash alike, so an upgrade keeps the plugin's version.
    """
    pinned = sorted((p["id"], p["sha256"]) for p in selection["policies"] if p.get("from", CATALOG) == CATALOG)
    ref = (selection.get("catalog") or {}).get("ref")
    return hashlib.sha256(json.dumps([ref, pinned]).encode("utf-8")).hexdigest()
