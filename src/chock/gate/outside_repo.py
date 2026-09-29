"""Which writes outside the repository a gate is allowed to see. Stdlib only; never imports chock.

A gate's `outside_repo` lists globs, absolute or starting with `~`. A write whose path leaves the
repository reaches the gate only when one matches; every other outside write is dropped, as it
always was. `~` is expanded here, at run time, for the machine running the hook, and Windows
spellings (drive letters, backslashes, letter case) compare the way Windows does.
"""

from __future__ import annotations

import fnmatch
import json
import os

OUTSIDE_KEY = "outside_repo"
_UP = ".."
_DRIVE_AT = 1
_SEPARATORS = ("/", "\\")


def _slashed(path):
    return str(path).replace("\\", "/")


def is_outside(path):
    """Whether a path as the runtime names it lies outside the repository: absolute, or climbing out."""
    text = _slashed(path)
    return text.startswith(("/", _UP + "/")) or text[_DRIVE_AT : _DRIVE_AT + 1] == ":" or text == _UP


def expand_home(pattern):
    """`~` (alone or before a separator) as this machine's home directory; anything else as given."""
    text = str(pattern)
    if text[:1] == "~" and (len(text) == 1 or text[1] in _SEPARATORS):
        return os.path.expanduser("~") + text[1:]
    return text


def _outside_fold(path):
    """`path` with `.` and `..` folded lexically and doubled slashes dropped; a root's leading slash kept."""
    parts = []
    for part in _slashed(path).split("/"):
        if part == _UP and parts and parts[-1] not in ("", _UP):
            parts.pop()
        elif part != "." and (part or not parts):
            parts.append(part)
    return "/".join(parts)


def declared_outside(path, root, patterns, *, windows=None):
    """The absolute, slash-separated path when it is outside `root` and matches a declared glob; else None."""
    windows = os.name == "nt" if windows is None else windows
    text = _slashed(path)
    if not is_outside(text) or not patterns:
        return None
    absolute = text if not text.startswith(_UP) else _slashed(root) + "/" + text
    absolute = _outside_fold(absolute)
    subject = absolute.lower() if windows else absolute
    for pattern in patterns:
        wanted = _outside_fold(expand_home(pattern))
        if fnmatch.fnmatchcase(subject, wanted.lower() if windows else wanted):
            return absolute
    return None


def outside_globs(gate):
    """The `outside_repo` globs the compiled gate declares; none when it declares none or cannot be read."""
    try:
        declared = json.loads(gate.read_text(encoding="utf-8")).get(OUTSIDE_KEY)
    except (OSError, ValueError, AttributeError):
        return []
    return [g for g in declared if isinstance(g, str)] if isinstance(declared, list) else []


def judged_files(files, root, patterns, repo_names):
    """`files` ({path: text}) keyed the way a gate judges them.

    A path inside the repository is named by `repo_names(path)`; one outside is kept, under its
    absolute path, only when a declared glob matches it.
    """
    kept = {}
    for path, text in files.items():
        for name in repo_names(path):
            if not is_outside(name):
                kept[name] = text
                continue
            found = declared_outside(name, root, patterns)
            if found is not None:
                kept[found] = text
    return kept
