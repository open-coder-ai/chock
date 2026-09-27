"""YAML parsing for chock: libyaml's safe loader when present, each distinct text parsed once."""

from __future__ import annotations

import copy
import functools
from typing import IO, Any

import yaml

#: libyaml's SafeLoader: the same safe schema, an order of magnitude faster than pure Python.
SAFE_LOADER = getattr(yaml, "CSafeLoader", yaml.SafeLoader)

_PARSED_TEXTS = 1024


@functools.lru_cache(maxsize=_PARSED_TEXTS)
def _parsed(text: str) -> Any:
    """The document `text` holds. Keyed on the text itself, so a rewritten file can never read stale."""
    return yaml.load(text, Loader=SAFE_LOADER)  # noqa: S506 -- SAFE_LOADER is a SafeLoader


def safe_load(source: str | IO[str]) -> Any:
    """`yaml.safe_load`, with a private copy of the result so no caller sees another's edits."""
    text = source if isinstance(source, str) else source.read()
    return copy.deepcopy(_parsed(text))
