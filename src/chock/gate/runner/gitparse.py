"""Gate runner: parsing what git prints -- `-z` path listings and unified diffs -- failing closed."""

from __future__ import annotations

import re
from collections import Counter


# >>> gate.py 22
class ListingError(Exception):
    """A git path listing the runner could not read: the gate refuses rather than judge a change it cannot see."""


class DiffError(ListingError):
    """A `git diff` the runner could not read or parse: the gate refuses rather than judge part of a change."""


#: Lines git writes between `diff --git` and a file's first hunk.
_DIFF_HEADERS = (
    "old mode ",
    "new mode ",
    "deleted file mode ",
    "new file mode ",
    "copy from ",
    "copy to ",
    "rename from ",
    "rename to ",
    "similarity index ",
    "dissimilarity index ",
    "index ",
    "--- ",
    "+++ ",
    "Binary files ",
)
_HUNK_RE = re.compile(r"@@ -\d+(?:,(\d+))? \+\d+(?:,(\d+))? @@")


def _hunk_line(line: str, old: int, new: int, sides: tuple[list[str], list[str]]) -> tuple[int, int]:
    """Place one line inside a hunk by its first character; returns the counts still owed."""
    mark, content = line[:1], line[1:]
    if mark == "+" and new:
        sides[0].extend(content.splitlines() or [""])
        return old, new - 1
    if mark == "-" and old:
        sides[1].extend(content.splitlines() or [""])
        return old - 1, new
    if mark == " " and old and new:
        return old - 1, new - 1
    if mark == "\\":
        return old, new
    msg = f"git diff has a hunk line it cannot place: {line[:40]!r}"
    raise DiffError(msg)


def _diff_sides(text: str) -> tuple[list[str], list[str]]:
    """(added, removed) lines of a unified diff. Headers only before a file's first hunk; inside one, the
    first character classifies a line and the hunk's counts bound it. Raises DiffError on anything else."""
    if text and not text.endswith("\n"):
        msg = "git diff does not end with a newline"
        raise DiffError(msg)
    sides: tuple[list[str], list[str]] = ([], [])
    old = new = 0
    in_file = False
    for line in text.split("\n")[:-1]:
        hunk = _HUNK_RE.match(line)
        if old or new:
            old, new = _hunk_line(line, old, new, sides)
        elif line.startswith("diff --git "):
            in_file = True
        elif in_file and hunk:
            old, new = (int(n) if n is not None else 1 for n in hunk.groups())
        elif not (in_file and line.startswith((*_DIFF_HEADERS, "\\"))):
            msg = f"git diff has a line outside any hunk: {line[:40]!r}"
            raise DiffError(msg)
    if old or new:
        msg = "git diff ends inside a hunk"
        raise DiffError(msg)
    return sides


def _diff_chunks(text: str) -> list[str]:
    """`text` split into one unified diff per file, at each line that opens a file's `diff --git` header."""
    starts = [match.start() for match in re.finditer(r"^diff --git ", text, re.MULTILINE)]
    if text and (not starts or starts[0]):
        msg = "git diff has a line outside any file"
        raise DiffError(msg)
    return [text[a:b] for a, b in zip(starts, [*starts[1:], len(text)], strict=True)]


def _drop_moved(lines: list[str], budget: dict[str, int]) -> list[str]:
    """`lines` without the ones `budget` still owes cancelling, spending it one for one."""
    kept = []
    for line in lines:
        key = line.strip()
        if budget.get(key):
            budget[key] -= 1
        else:
            kept.append(line)
    return kept


def cancel_moved(files: list[tuple[list[str], list[str]]]) -> list[tuple[list[str], list[str]]]:
    """Each file's (added, removed) without the lines the change only moves or re-indents.

    An added line cancels against one removed line equal to it after stripping leading and trailing
    whitespace, in any file of the change; each removed line cancels at most one added line. The
    removed side drops the same pairs, so a moved line is neither added nor removed.
    """
    adds = Counter(line.strip() for added, _ in files for line in added)
    gone = Counter(line.strip() for _, removed in files for line in removed)
    pairs = dict(adds & gone)
    add_budget, gone_budget = dict(pairs), dict(pairs)
    return [(_drop_moved(added, add_budget), _drop_moved(removed, gone_budget)) for added, removed in files]


def _nul_paths(out: bytes) -> list[str]:
    """Paths from a `-z` listing, verbatim. Raises ListingError on anything but NUL-terminated UTF-8 entries."""
    if not out:
        return []
    entries = out.split(b"\0")
    if entries.pop() or not all(entries):
        msg = "git listed paths that are not NUL-terminated"
        raise ListingError(msg)
    try:
        return [entry.decode("utf-8") for entry in entries]
    except UnicodeDecodeError as exc:
        msg = f"git listed a path that is not UTF-8 ({exc.reason})"
        raise ListingError(msg) from exc
