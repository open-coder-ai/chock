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


def nests_deeper_than(text: str, limit: int) -> bool:
    """Whether any node of `text` nests deeper than `limit`, counted from parser events before anything is composed.

    Libyaml's composer can crash the process on deep nesting of any spelling (flow, indented or compact
    block), so the depth is measured on the event stream, which it keeps on the heap. Text the parser
    rejects is reported as not too deep: the loader then raises its own error for it.
    """
    depth = 0
    try:
        for event in yaml.parse(text, Loader=SAFE_LOADER):
            if isinstance(event, (yaml.SequenceStartEvent, yaml.MappingStartEvent)):
                depth += 1
                if depth > limit:
                    return True
            elif isinstance(event, (yaml.SequenceEndEvent, yaml.MappingEndEvent)):
                depth -= 1
    except yaml.YAMLError:
        return False
    return False
