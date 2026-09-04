"""Spec prose that quotes a `field: value` pair must quote one the schema accepts."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC_DIR = ROOT / "spec"
SCHEMA_DIR = ROOT / "src" / "chock" / "validation" / "schemas"

# Each entry: the prose token, and where in which schema its permitted values live.
FIELDS = {
    "action": ("manifest.hook.json", ("properties", "gate", "properties", "action")),
    "enforcement": ("manifest.schema.json", ("properties", "enforcement")),
}


def _allowed(schema_file: str, path: tuple[str, ...]) -> set[str]:
    node = json.loads((SCHEMA_DIR / schema_file).read_text(encoding="utf-8"))
    for key in path:
        node = node[key]
    if "const" in node:
        return {node["const"]}
    return set(node["enum"])


def _claims(field: str) -> list[tuple[Path, int, str]]:
    """Every `` `field: value` `` the spec asserts, with the line that asserts it."""
    pattern = re.compile(rf"`{re.escape(field)}:\s*([a-z][a-z0-9_-]*)`")
    found = []
    for path in sorted(SPEC_DIR.glob("*.md")):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            found.extend((path, number, m.group(1)) for m in pattern.finditer(line))
    return found


def test_the_spec_makes_such_claims_at_all() -> None:
    """A regex that matched nothing would make the test below vacuously green."""
    assert any(_claims(field) for field in FIELDS), "no `field: value` claims found in spec/"


@pytest.mark.parametrize("field", sorted(FIELDS))
def test_spec_field_values_are_accepted_by_the_schema(field: str) -> None:
    allowed = _allowed(*FIELDS[field])
    bad = [
        f"{path.name}:{number} claims `{field}: {value}`"
        for path, number, value in _claims(field)
        if value not in allowed
    ]
    assert not bad, (
        f"The spec asserts a `{field}` value the schema cannot express: {bad}. "
        f"{FIELDS[field][0]} accepts only {sorted(allowed)}. Either the schema is behind the spec "
        f"and should gain the value, or the prose names the wrong field -- SEC-3 was the latter, "
        f"conflating `gate.action` (a const) with `enforcement` (an enum)."
    )
