"""Every repo-relative name a write is judged under: as written, through symlinks, and in the case the disk stores.

Extracted into the vendored per-agent runtime beside write_gate, so it is stdlib-only and may not import chock.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path, PurePosixPath, PureWindowsPath

from .outside_repo import is_outside
from .workspace_root import _DRIVE_COLON, _folded

#: Filesystems that fold case: a differently-cased spelling of a protected path writes the protected file.
_CASE_BLIND = sys.platform in ("darwin", "win32")


def repo_relative(path, root):
    """`path` relative to `root` in POSIX form, as scope globs are written; as given when outside `root`."""
    text = str(path)
    if root is None:
        return text
    windows = os.name == "nt" or str(root)[1:2] == _DRIVE_COLON
    flavour = PureWindowsPath if windows else PurePosixPath
    try:
        return _folded(flavour(str(root)) / text).relative_to(flavour(str(root))).as_posix()
    except ValueError:
        pass
    if windows != (os.name == "nt"):
        return text
    try:
        return Path(root, text).resolve().relative_to(Path(root).resolve()).as_posix()
    except (OSError, ValueError, RuntimeError):
        return text


def on_disk_case(name, root):
    """`name` (repo-relative, POSIX) with each existing component spelled as the filesystem stores it."""
    here, spelled = Path(root), []
    for part in PurePosixPath(name).parts:
        try:
            stored = os.listdir(here)
        except OSError:
            stored = []
        found = part if part in stored else next((s for s in stored if s.casefold() == part.casefold()), part)
        spelled.append(found)
        here = here / found
    return PurePosixPath(*spelled).as_posix()


def repo_paths(path, root, *, case_blind=_CASE_BLIND):
    """Every repo-relative name a write is judged under: as written, and through symlinks and case."""
    lexical = repo_relative(path, root)
    if root is None or (str(root)[1:2] == _DRIVE_COLON) != (os.name == "nt"):
        return (lexical,)
    try:
        resolved = Path(root, str(path)).resolve().relative_to(Path(root).resolve()).as_posix()
    except (OSError, ValueError, RuntimeError):
        return (lexical,)
    names = [lexical, resolved]
    if case_blind:
        names += [on_disk_case(name, root) for name in (lexical, resolved) if not is_outside(name)]
    return tuple(dict.fromkeys(names))
