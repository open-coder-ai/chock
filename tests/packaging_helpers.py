"""Shared helpers for tests that compare built package trees."""

from __future__ import annotations

from pathlib import Path


def tree_bytes(root: Path) -> dict[str, bytes]:
    """Every file under `root`, by relative path, as bytes."""
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}
