"""Shared stderr diagnostics: one place owning the `[WARN]`/`[ERROR]` prefix convention."""

from __future__ import annotations

import sys


def warn(message: str) -> None:
    print(f"[WARN] {message}", file=sys.stderr)  # noqa: T201 -- the designated output surface


def error(message: str) -> None:
    print(f"[ERROR] {message}", file=sys.stderr)  # noqa: T201 -- the designated output surface
