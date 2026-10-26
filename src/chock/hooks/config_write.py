"""Writes of a vendor's hook config that follow no link: the check and the write both go through `mcp_write`."""

from __future__ import annotations

import json
import os
from pathlib import Path

from chock.scaffold.mcp_write import _lstat_checked, remove_file, write_file

CONFIG_MODE = 0o600


def check_unlinked(repo_root: Path, rel: Path) -> bool:
    """Refuse a link or a non-regular file anywhere on `rel`; True when the file exists."""
    return _lstat_checked(Path(repo_root), rel.as_posix()) is not None


def write_json(repo_root: Path, rel: Path, doc: object) -> None:
    """Replace `rel` with `doc` as JSON, every directory on the way created or pinned without following a link."""
    write_file(Path(repo_root), rel.as_posix(), json.dumps(doc, indent=2).encode("utf-8"), CONFIG_MODE)


def remove(repo_root: Path, rel: Path) -> None:
    """Delete `rel` when present; a link on the way is refused."""
    if check_unlinked(repo_root, rel) and os.path.lexists(Path(repo_root) / rel):
        remove_file(Path(repo_root), rel.as_posix())
