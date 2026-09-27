"""The files a Codex `apply_patch` call would leave behind, for a gate that judges whole files.

Codex CLI writes files with one tool, apply_patch, whose only argument is the patch text in
`tool_input.command`: no path, no content. The write gate therefore had nothing to judge before
the write, and Codex was checked only at the turn's end. The patch format is Codex's own,
documented grammar::

    *** Begin Patch
    *** Add File: <path>          lines follow, each prefixed "+"
    *** Delete File: <path>
    *** Update File: <path>
    *** Move to: <new path>       optional
    @@ <optional anchor line>
     context / -removed / +added  lines of one hunk
    *** End of File               optional: the hunk ends the file
    *** End Patch

Each added or updated file is rebuilt as the patch would leave it, from the file on disk. A
hunk that cannot be placed leaves that file out, as the call itself would fail; the turn's end
judges whatever lands. Extracted into the vendored runtime, so stdlib-only.
"""

from __future__ import annotations

from pathlib import Path

_BEGIN = "*** Begin Patch"
_END = "*** End Patch"
_ADD = "*** Add File: "
_DELETE = "*** Delete File: "
_UPDATE = "*** Update File: "
_MOVE = "*** Move to: "
_EOF = "*** End of File"
_HUNK = "@@"
_OPS = (("add", _ADD), ("delete", _DELETE), ("update", _UPDATE))


def patch_text(event):
    """The patch an apply_patch call carries, from its first to its last marker; None otherwise."""
    raw = getattr(event, "raw", None)
    tool_input = raw.get("tool_input") if isinstance(raw, dict) else None
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    if isinstance(command, list):
        command = "\n".join(part for part in command if isinstance(part, str))
    start = command.find(_BEGIN) if isinstance(command, str) else -1
    end = command.find(_END, start) if start >= 0 else -1
    return command[start : end + len(_END)] if end >= 0 else None


def _body_line(current, line):
    """Add one line under the file operation `current` is reading."""
    if line.startswith(_MOVE):
        current[2] = line[len(_MOVE) :].strip()
    elif line.startswith(_HUNK):
        current[3].append([line[len(_HUNK) :].strip(), [], False])
    elif line.startswith(_EOF):
        if current[3]:
            current[3][-1][2] = True
    elif current[0] == "add":
        current[3].append(line[1:] if line.startswith("+") else line)
    else:
        if not current[3]:
            current[3].append(["", [], False])
        current[3][-1][1].append(line if line[:1] in (" ", "-", "+") else " " + line)


def parse_patch(patch):
    """[(op, path, moved_to, hunks)]: op is add/delete/update; a hunk is (anchor, lines, at_eof)."""
    operations = []
    for line in patch.replace("\r\n", "\n").split("\n")[1:]:
        if line.startswith(_END):
            break
        opened = next(((op, marker) for op, marker in _OPS if line.startswith(marker)), None)
        if opened is not None:
            operations.append([opened[0], line[len(opened[1]) :].strip(), None, []])
        elif operations:
            _body_line(operations[-1], line)
    return [tuple(operation) for operation in operations]


def _find(lines, wanted, start):
    """Where `wanted` starts in `lines` at or after `start`, exactly or ignoring trailing space."""
    for loose in (False, True):
        for index in range(start, len(lines) - len(wanted) + 1):
            window = lines[index : index + len(wanted)]
            if window == wanted or (loose and [w.rstrip() for w in window] == [w.rstrip() for w in wanted]):
                return index
    return None


def apply_hunks(text, hunks):
    """`text` with the hunks applied in order, or None when one cannot be placed."""
    lines = text.split("\n")
    cursor = 0
    for anchor, body, at_eof in hunks:
        if anchor:
            found = _find(lines, [anchor], cursor)
            if found is None:
                found = next((i for i in range(cursor, len(lines)) if anchor.strip() in lines[i]), None)
            if found is None:
                return None
            cursor = found + 1
        old = [line[1:] for line in body if line[:1] in (" ", "-")]
        new = [line[1:] for line in body if line[:1] in (" ", "+")]
        if not old:
            at = len(lines) - (1 if lines and lines[-1] == "" else 0) if at_eof else cursor
        else:
            at = _find(lines, old, cursor)
            if at is None:
                return None
        lines[at : at + len(old)] = new
        cursor = at + len(new)
    return "\n".join(lines)


def _read(root, path):
    target = Path(path)
    if not target.is_absolute():
        target = Path(root if root is not None else Path.cwd()) / target
    try:
        return target.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def patched_files(event, root=None):
    """{path: text} for every file an apply_patch call adds or updates and can be rebuilt."""
    patch = patch_text(event)
    if patch is None:
        return {}
    files = {}
    for op, path, moved_to, body in parse_patch(patch):
        if op == "add":
            files[path] = "\n".join(body) + "\n"
        elif op == "update":
            before = _read(root, path)
            after = apply_hunks(before, body) if before is not None else None
            if after is not None:
                files[moved_to or path] = after
    return files


def patch_added(event):
    """{path: the lines the patch adds}, which is what `added_lines` means for it."""
    patch = patch_text(event)
    if patch is None:
        return {}
    added = {}
    for op, path, moved_to, body in parse_patch(patch):
        if op == "add":
            added[path] = "\n".join(body)
        elif op == "update":
            added[moved_to or path] = "\n".join(line[1:] for _, hunk, _ in body for line in hunk if line[:1] == "+")
    return added
