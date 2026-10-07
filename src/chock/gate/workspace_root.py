"""Which workspace root an event is judged in, from the client's own `workspace_roots`. Stdlib only; never imports chock.

Cursor sends no `cwd` and spells a Windows root `/C:/x`. Measured live: Cursor 3.22.12 on Windows, 2026-10-06.
"""

from __future__ import annotations

from pathlib import PurePosixPath, PureWindowsPath

_PARENT = ".."
#: A Windows root is spelled with a drive (`C:`), which a POSIX root never is.
_DRIVE_COLON = ":"
_ROOTS_KEY = "workspace_roots"


def _folded(pure):
    """`pure` with `..` folded lexically; an absolute path never climbs above its anchor."""
    parts = []
    for part in pure.parts:
        if part != _PARENT:
            parts.append(part)
        elif len(parts) > 1:
            parts.pop()
    return type(pure)(*parts)


def _workspace_root(text):
    """A workspace root as a path: `/C:/x` is `C:/x`; anything else as given."""
    if text[:1] == "/" and text[2:3] == _DRIVE_COLON and text[1:2].isalpha() and text[3:4] in ("", "/", "\\"):
        return text[1:]
    return text


def _holds(root, path):
    """Whether `path`, absolute or relative, lies under `root`, compared the way `root` is spelled."""
    flavour = PureWindowsPath if root[1:2] == _DRIVE_COLON else PurePosixPath
    try:
        _folded(flavour(root) / str(path)).relative_to(flavour(root))
    except ValueError:
        return False
    return True


def workspace_roots(event):
    """The folders the client says the agent works in, normalised; [] when it names none."""
    raw = getattr(event, "raw", None)
    roots = raw.get(_ROOTS_KEY) if isinstance(raw, dict) else None
    if not isinstance(roots, list):
        return []
    return [_workspace_root(root) for root in roots if isinstance(root, str) and root]


def workspace_root(event):
    """The workspace root holding the event's path, else the first one; None when the client names none."""
    roots = workspace_roots(event)
    path = getattr(event, "path", None)
    return next((root for root in roots if path and _holds(root, path)), roots[0] if roots else None)
