"""Path folding for the self-protection guard: case, slashes, dots, braces, globs and links (stdlib only)."""

from __future__ import annotations

import fnmatch
import os
import posixpath
import re
from pathlib import Path

_GLOB = re.compile(r"[*?\[]")
_BRACES = re.compile(r"\{([^{}]*)\}")


def fold(path: str) -> str:
    """`path` lower-cased, backslashes read as slashes, `//`, `/./` and `..` folded."""
    text = path.replace("\\", "/").lower()
    if not text:
        return text
    return posixpath.normpath(re.sub(r"/{2,}", "/", text))


def braces(text: str) -> list[str]:
    """Every spelling a brace list stands for (`{a,b}`), at most a few dozen."""
    found, todo = [], [text]
    while todo and len(found) < 64:  # noqa: PLR2004 -- a bound on expansion, not a rule
        item = todo.pop()
        match = _BRACES.search(item)
        if match is None:
            found.append(item)
            continue
        todo += [item[: match.start()] + part + item[match.end() :] for part in match.group(1).split(",")]
    return found


def base_is(text: str, wanted: str) -> bool:
    """Whether the last segment of a folded path is `wanted`, or a glob or brace list that can name it."""
    for spelling in braces(text):
        base = spelling.rstrip("/").rsplit("/", 1)[-1]
        if base == wanted or (_GLOB.search(base) and fnmatch.fnmatchcase(wanted, base)):
            return True
    return False


def real_path(token: str, cwd: Path) -> str:
    """The folded path `token` names once `~` is expanded and links are followed, from `cwd`."""
    try:
        return fold(os.path.realpath(os.path.join(cwd, os.path.expanduser(token))))
    except (OSError, ValueError):
        return ""
