"""The floor's control plane: the paths that define the guardrails, and what the base says to do when one changes.

No file is read for meaning: a listed path that changed is reported, whatever the change. The base's
`.chock/config.yaml` alone sets the outcome and the patterns; the head's config is never read.
"""

from __future__ import annotations

import fnmatch
import json
import unicodedata
from dataclasses import dataclass
from importlib import resources

import yaml

from chock import yamlio
from chock.validation.floor_git import FloorError, Revision

RULE = "floor/control-plane-changed"
REFUSE, LISTED = "refuse", "listed"
_MODES = (REFUSE, LISTED)
_CONFIG = ".chock/config.yaml"
_SECTION, _MODE, _PATHS = "floor", "control_plane", "control_plane_paths"
_EDITS = ("add", "remove")
_FORMAT = "Cf"


def default_patterns() -> tuple[str, ...]:
    text = resources.files("chock").joinpath("data/control_plane.json").read_text(encoding="utf-8")
    return tuple(json.loads(text)["paths"])


def folded(path: str) -> str:
    """`path` as a case-blind, normalising filesystem may open it: NFC, no format characters, case folded,
    and no trailing dot or space on any component (Windows drops them)."""
    text = "".join(c for c in unicodedata.normalize("NFC", path) if unicodedata.category(c) != _FORMAT)
    return "/".join(part.rstrip(". ") for part in text.casefold().split("/"))


@dataclass(frozen=True)
class ControlPlane:
    mode: str
    patterns: tuple[str, ...]

    def covers(self, path: str) -> bool:
        name = folded(path)
        return any(fnmatch.fnmatchcase(name, folded(pattern)) for pattern in self.patterns)


def _invalid(what: str) -> FloorError:
    return FloorError(f"the base's {_CONFIG} {_SECTION}.{what}")


def _section(base: Revision) -> dict:
    text = base.text(_CONFIG)
    try:
        doc = yamlio.safe_load(text) if text else None
    except yaml.YAMLError as exc:
        msg = "could not be read as YAML"
        raise _invalid(msg) from exc
    section = doc.get(_SECTION) if isinstance(doc, dict) else None
    if section is not None and not isinstance(section, dict):
        msg = "is not a mapping"
        raise _invalid(msg)
    return section or {}


def _edits(section: dict) -> dict[str, list[str]]:
    edits = section.get(_PATHS) or {}
    if not isinstance(edits, dict) or set(edits) - set(_EDITS):
        msg = f"{_PATHS} takes only {' and '.join(_EDITS)}"
        raise _invalid(msg)
    found = {key: edits.get(key) or [] for key in _EDITS}
    if any(not isinstance(v, list) or not all(isinstance(p, str) and p for p in v) for v in found.values()):
        msg = f"{_PATHS} lists must hold path patterns"
        raise _invalid(msg)
    return found


def from_base(base: Revision) -> ControlPlane:
    """The control plane the base defines; FloorError (undecided) for a `floor:` section it cannot read."""
    section = _section(base)
    mode = section.get(_MODE, REFUSE)
    if mode not in _MODES:
        msg = f"{_MODE} is {mode!r}; it takes {' or '.join(_MODES)}"
        raise _invalid(msg)
    edits = _edits(section)
    kept = tuple(p for p in default_patterns() if p not in edits["remove"])
    return ControlPlane(mode, kept + tuple(edits["add"]))
