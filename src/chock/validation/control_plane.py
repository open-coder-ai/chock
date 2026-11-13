"""The floor's control plane: the paths that define the guardrails, and what the base says to do when one changes.

No file is read for meaning: a listed path that changed is reported, whatever the change. The base's
`.chock/config.yaml` alone sets the outcome and the patterns; the head's config is never read.
"""

from __future__ import annotations

import dataclasses
import fnmatch
import functools
import json
import posixpath
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
_SYMLINK = "120000"
_GLOB = frozenset("*?[")


def default_patterns() -> tuple[str, ...]:
    text = resources.files("chock").joinpath("data/control_plane.json").read_text(encoding="utf-8")
    return tuple(json.loads(text)["paths"])


@functools.lru_cache(maxsize=8192)
def folded(path: str) -> str:
    """`path` as a case-blind, normalising filesystem may open it: NFC, no format characters, case folded,
    and no trailing dot or space on any component (Windows drops them)."""
    text = "".join(c for c in unicodedata.normalize("NFC", path) if unicodedata.category(c) != _FORMAT)
    return "/".join(part.rstrip(". ") for part in text.casefold().split("/"))


@functools.cache
def _parents(pattern: str) -> set[str]:
    """The folders a pattern lies under, up to its first glob: a symlink or gitlink there redirects the pattern."""
    parts = folded(pattern).split("/")
    literal = parts[: next((i for i, p in enumerate(parts) if _GLOB & set(p)), len(parts))]
    return {"/".join(literal[:k]) for k in range(1, len(literal) + 1) if k < len(parts)}


@dataclass(frozen=True)
class ControlPlane:
    mode: str
    patterns: tuple[str, ...]
    added: tuple[str, ...] = ()
    removed: tuple[str, ...] = ()
    #: (folded in-repo target, link path) for each symlink the control plane reaches through, at base or head.
    links: tuple[tuple[str, str], ...] = ()

    def _direct(self, name: str) -> bool:
        return any(fnmatch.fnmatchcase(name, folded(p)) or name in _parents(p) for p in self.patterns)

    def covers(self, path: str, _depth: int = 0) -> bool:
        """Whether `path`, or the path a client opens through a symlinked control-plane folder, is control plane."""
        name = folded(path)
        if self._direct(name):
            return True
        if _depth > len(self.links):
            return False
        rests = ((link, _under(name, target)) for target, link in self.links)
        return any(self.covers(link + rest, _depth + 1) for link, rest in rests if rest is not None)

    def summary(self) -> str:
        """The list in force: mode, size, and the base's own edits to the defaults."""
        added, removed = ", ".join(self.added) or "none", ", ".join(self.removed) or "none"
        return (
            f"control plane: {self.mode}, {len(self.patterns)} pattern(s); base added: {added}; base removed: {removed}"
        )


def _under(name: str, target: str) -> str | None:
    """`name` relative to `target` ("" when equal, "/rest" below it; the root is ""), None when outside it."""
    if not target:
        return f"/{name}"
    if name == target or name.startswith(f"{target}/"):
        return name[len(target) :]
    return None


def _target(link: str, data: bytes | None) -> str | None:
    """The in-repo folder or file a committed symlink names; None when it leaves the repository."""
    if not data:
        return None
    joined = posixpath.normpath(posixpath.join(posixpath.dirname(link), data.decode("utf-8", "replace")))
    if posixpath.isabs(joined) or joined.split("/")[0] == "..":
        return None
    return "" if joined == "." else folded(joined)


def through_links(plane: ControlPlane, *revisions: Revision) -> ControlPlane:
    """`plane` plus every in-repo target of a symlink it covers at any of `revisions`, followed to a fixed point."""
    symlinks = [(rev, path) for rev in revisions for path, (mode, _) in rev.entries().items() if mode == _SYMLINK]
    links: list[tuple[str, str]] = []
    grew = True
    while grew:
        grew = False
        current = dataclasses.replace(plane, links=tuple(links))
        for rev, path in symlinks:
            target = _target(path, rev.blob(path)) if current.covers(path) else None
            if target is not None and (target, folded(path)) not in links:
                links.append((target, folded(path)))
                grew = True
    return dataclasses.replace(plane, links=tuple(links))


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
    edits, defaults = _edits(section), default_patterns()
    unknown = [p for p in edits["remove"] if p not in defaults]
    if unknown:
        msg = f"{_PATHS}.remove names {unknown!r}, which is no default pattern"
        raise _invalid(msg)
    kept = tuple(p for p in defaults if p not in edits["remove"])
    return ControlPlane(mode, kept + tuple(edits["add"]), tuple(edits["add"]), tuple(edits["remove"]))
