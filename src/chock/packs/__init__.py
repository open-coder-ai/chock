"""Packaged content for distribution in the chock wheel/binary."""

from __future__ import annotations

from pathlib import Path

try:
    from importlib.resources.abc import Traversable
except ImportError:  # pragma: no cover - Python <3.11 compatibility
    from pathlib import Path as Traversable  # type: ignore[misc, assignment]

from chock.resources import package_data_dir


def packs_root() -> Traversable:
    """Return the root of bundled package data for chock.packs."""
    return package_data_dir("chock.packs")


def to_path(traversable: Traversable) -> Path:
    """Best-effort conversion of a Traversable to a concrete Path."""
    if isinstance(traversable, Path):
        return traversable
    return Path(str(traversable))


__all__ = ["Traversable", "packs_root", "to_path"]
