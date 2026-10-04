"""Read a selection (file, `#s=` URL or bare base64url code) and check it against its schema."""

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


def check(data: Any) -> dict[str, Any]:
    """`data` if it is a schema-valid selection with unique policy ids, else SelectionError."""
    validator = jsonschema.Draft7Validator(load_schema(SCHEMA))
    errors = sorted(validator.iter_errors(data), key=lambda e: list(e.path))
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


def load(arg: str) -> dict[str, Any]:
    """The checked selection named by `arg`."""
    return check(_raw(arg))


def digest(selection: dict[str, Any]) -> str:
    """A stable hash of what a selection installs: the catalog commit and each policy's pinned hash."""
    pinned = sorted((p["id"], p["sha256"]) for p in selection["policies"])
    return hashlib.sha256(json.dumps([selection["catalog"]["ref"], pinned]).encode("utf-8")).hexdigest()
