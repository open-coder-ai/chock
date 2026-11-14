"""The floor's control plane: the paths that define the guardrails, and what the base says to do when one changes.

No file is read for meaning: a listed path that changed is reported, whatever the change. The base's
`.chock/config.yaml` alone sets the outcome and the patterns; the head's config is never read.
"""

from __future__ import annotations

import bisect
import dataclasses
import fnmatch
import functools
import json
import unicodedata
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

import yaml

from chock import yamlio
from chock.validation.floor_git import FloorError, Revision, changed_paths, history_states

RULE = "floor/control-plane-changed"
REFUSE, LISTED = "refuse", "listed"
_MODES = (REFUSE, LISTED)
_CONFIG = ".chock/config.yaml"
_SECTION, _MODE, _PATHS = "floor", "control_plane", "control_plane_paths"
_EDITS = ("add", "remove")
_FORMAT = "Cf"
_SYMLINK = "120000"
_REGULAR = ("100644", "100755")
_GLOB = frozenset("*?[")
_ANY_DEPTH = "**/"
_MAX_HOPS = 32


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


def _match(name: str, pattern: str) -> bool:
    """fnmatch on folded text; a leading `**/` also matches at the top level."""
    pat = folded(pattern)
    return fnmatch.fnmatchcase(name, pat) or (pat.startswith(_ANY_DEPTH) and fnmatch.fnmatchcase(name, pat[3:]))


@dataclass(frozen=True)
class ControlPlane:
    mode: str
    patterns: tuple[str, ...]
    added: tuple[str, ...] = ()
    removed: tuple[str, ...] = ()
    #: Entries of `added` that match no path at base or head, named as such in the summary.
    unmatched: tuple[str, ...] = ()
    #: Folded paths of the symlinks resolving a control-plane link passes through, at base or head.
    hops: frozenset[str] = frozenset()

    def _direct(self, name: str) -> bool:
        return any(_match(name, p) or _match(f"{name}/", p) or name in _parents(p) for p in self.patterns)

    def covers(self, path: str) -> bool:
        """Whether `path`, a folder above it that a client opens it through, or a link on the way, is control plane."""
        name = folded(path)
        return name in self.hops or self._direct(name)

    def deep_match(self, path: str) -> str | None:
        """The any-depth pattern that matches `path` only below the top level, so the output can say why."""
        name = folded(path)
        deep = (p for p in self.patterns if p.startswith(_ANY_DEPTH) and not fnmatch.fnmatchcase(name, folded(p)[3:]))
        return next((p for p in deep if _match(name, p) or _match(f"{name}/", p)), None)

    def changes(self, repo: Path, base: Revision, head: Revision) -> tuple[list[str], set[str]]:
        """(paths of the plane the tree diff changes or any commit leaves in a state the base lacks, those only
        in history)."""
        diff = {path for path in changed_paths(repo, base.sha, head.sha) if self.covers(path)}
        states = history_states(repo, base.sha, head.sha)
        history = {p for p, state in states if p not in diff and self.covers(p) and state != base.state(p)}
        return sorted(diff | history), history

    def summary(self) -> str:
        """The list in force: mode, size, and the base's own edits to the defaults."""
        shown = [f"{p} (matches nothing at base or head)" if p in self.unmatched else p for p in self.added]
        added, removed = ", ".join(shown) or "none", ", ".join(self.removed) or "none"
        return (
            f"control plane: {self.mode}, {len(self.patterns)} pattern(s); base added: {added}; base removed: {removed}"
        )


class _Tree:
    """One revision's symlinks, gitlinks and paths, folded, for resolving links from tree data alone."""

    def __init__(self, rev: Revision) -> None:
        entries = rev.entries()
        self.rev = rev
        self.links = {folded(p): p for p, (mode, _) in entries.items() if mode == _SYMLINK}
        self.gitlinks = {folded(p) for p in rev.gitlinks()}
        self.files = {folded(p) for p in entries} | self.gitlinks
        self.folders = {f.rsplit("/", k)[0] for f in self.files for k in range(1, f.count("/") + 1)}
        self._sorted = sorted(self.files)

    def resolve(self, link: str) -> tuple[str, list[str]]:
        """(folded in-repo path `link` opens, links passed); FloorError naming the link when it cannot resolve."""
        todo, done, hops = link.split("/"), [], []
        while todo:
            part = todo.pop(0)
            part = part if part == ".." else folded(part)
            if not part:
                continue
            if part == "..":
                if not done:
                    raise _unresolved(link, self.rev, "its target leaves the repository")
                done.pop()
                continue
            here = "/".join([*done, part])
            if here in self.gitlinks and todo:
                raise _unresolved(link, self.rev, f"its target passes through the submodule {here}")
            if here not in self.links:
                done.append(part)
                continue
            hops.append(here)
            if len(hops) > _MAX_HOPS:
                raise _unresolved(link, self.rev, f"more than {_MAX_HOPS} links (a loop?)")
            target = (self.rev.blob(self.links[here]) or b"").decode("utf-8", "replace")
            if not target or target.startswith("/") or "\\" in target or ":" in target.split("/")[0]:
                raise _unresolved(link, self.rev, f"{here} has the absolute or empty target {target!r}")
            todo[:0] = target.split("/")
        return "/".join(done), hops

    def exists(self, name: str) -> bool:
        return not name or name in self.files or name in self.folders

    def below(self, folder: str) -> list[str]:
        """The folded paths under `folder` (the root when "")."""
        if not folder:
            return self._sorted
        start = bisect.bisect_left(self._sorted, f"{folder}/")
        return self._sorted[start : bisect.bisect_left(self._sorted, f"{folder}0")]  # "0" sorts right after "/"


def _unresolved(link: str, rev: Revision, why: str) -> FloorError:
    return FloorError(
        f"control plane: the symbolic link {link} at {rev.sha[:12]} does not resolve inside the repository: {why}; "
        "replace the link with real files"
    )


def _opens_control_plane(plane: ControlPlane, tree: _Tree, name: str) -> tuple[str, list[str]] | None:
    """(target, links passed) when the link `name` is a control-plane root, inside one, or above one; else None."""
    if plane.covers(name):
        return tree.resolve(tree.links[name])
    try:
        target, passed = tree.resolve(tree.links[name])
    except FloorError:
        return None  # leaves the repository: nothing committed lies under it
    rests = (f[len(target) :] if target else f"/{f}" for f in tree.below(target))
    return (target, passed) if any(plane.covers(name + rest) for rest in rests) else None


def closed_under_links(plane: ControlPlane, *revisions: Revision) -> ControlPlane:
    """`plane` plus every link a control-plane link passes through, once each link at, inside or above the control
    plane at each of `revisions` opens a control-plane path or nothing; FloorError (undecided) naming one that does not."""
    hops: set[str] = set()
    for rev in revisions:
        tree = _Tree(rev)
        for name, link in sorted(tree.links.items()):
            found = _opens_control_plane(plane, tree, name)
            if found is None:
                continue
            target, passed = found
            hops.update(passed)
            if tree.exists(target) and not plane.covers(target):
                shown = target or "."
                msg = (
                    f"control plane: the symbolic link {link} at {rev.sha[:12]} opens {shown}, which is not control "
                    f"plane; put {shown}/** on floor.{_PATHS}.add in the base's {_CONFIG}, or replace the link with "
                    "real files"
                )
                raise FloorError(msg)
    return dataclasses.replace(plane, hops=frozenset(hops))


def _invalid(what: str) -> FloorError:
    return FloorError(f"the base's {_CONFIG} {_SECTION}.{what}")


def _section(base: Revision) -> dict:
    state = base.state(_CONFIG)
    if base.paths(f"{_CONFIG}/") or (state is not None and state[0] not in _REGULAR):
        msg = (
            f"the base's {_CONFIG} is a folder, a symbolic link or a submodule, not a file; the floor reads only a file"
        )
        raise FloorError(msg)
    try:
        text = (base.blob(_CONFIG) or b"").decode("utf-8")
        doc = yamlio.safe_load(text) if text else None
    except UnicodeDecodeError as exc:
        msg = f"the base's {_CONFIG} is not UTF-8"
        raise FloorError(msg) from exc
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


def _added(entries: list[str], revisions: tuple[Revision, ...]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """(patterns, entries matching no path at any of `revisions`) for the base's `add:`; `name/` means `name/**`.
    FloorError (undecided) for a bare entry naming a folder, which as written would match only the folder itself."""
    trees = [_Tree(rev) for rev in revisions] if entries else []
    patterns, unmatched = [], []
    for entry in entries:
        if not _GLOB & set(entry) and not entry.endswith("/") and any(folded(entry) in t.folders for t in trees):
            msg = f"{_PATHS}.add names {entry!r}, a folder; write {entry + '/**'!r} for the folder and everything in it"
            raise _invalid(msg)
        pattern = f"{entry}**" if entry.endswith("/") else entry
        alone = ControlPlane(REFUSE, (pattern,))
        if not any(alone.covers(f) for t in trees for f in t.files | t.folders):
            unmatched.append(entry)
        patterns.append(pattern)
    return tuple(patterns), tuple(unmatched)


def from_base(base: Revision, head: Revision) -> ControlPlane:
    """The control plane the base defines; FloorError (undecided) for a `floor:` section it cannot read."""
    section = _section(base)
    mode = section.get(_MODE, REFUSE)
    if mode not in _MODES:
        msg = f"{_MODE} is {mode!r}; it takes {' or '.join(_MODES)}"
        raise _invalid(msg)
    edits, defaults = _edits(section), default_patterns()
    unknown = [p for p in edits["remove"] if p not in defaults]
    if unknown:
        hint = [f"{_ANY_DEPTH}{p}" for p in unknown if f"{_ANY_DEPTH}{p}" in defaults]
        msg = f"{_PATHS}.remove names {unknown!r}, which is no default pattern" + (
            f"; write {hint[0]!r}" if hint else ""
        )
        raise _invalid(msg)
    kept = tuple(p for p in defaults if p not in edits["remove"])
    added, unmatched = _added(edits["add"], (base, head))
    return ControlPlane(mode, kept + added, tuple(edits["add"]), tuple(edits["remove"]), unmatched)
